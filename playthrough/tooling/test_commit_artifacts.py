#!/usr/bin/env python3
"""Regression suite for playthrough/tooling/commit_artifacts.sh.

The commit lifecycle is the one part of this feature whose failure is
invisible in the artifacts themselves: every frame, the film and the
transcript can be perfect while the history still shows a single bundled
commit that cannot distinguish a session that was played from one that
was assembled.  This suite holds the properties that make the history
evidence:

    python3 playthrough/tooling/test_commit_artifacts.py
    python3 -B -m unittest discover -s playthrough/tooling -p 'test_*.py'

WHAT IS ASSERTED

* IT NEVER WRITES GIT CONFIGURATION.  Not user.name, not user.email, in
  no scope, on no path -- asserted against the SOURCE, so no run can
  pass by not happening to reach the line, and against the sandbox's own
  .git/config, which is inspected as a file rather than through the
  command whose absence is the point.
* AN IDENTITY THAT DOES NOT RESOLVE IS A REFUSAL.  `git var
  GIT_AUTHOR_IDENT` failing means no commit, rather than a commit
  attributed to whatever git derived from the passwd entry.  A split
  author/committer attribution is refused too.
* THE TWO CHECKPOINTS ARE ORDERED.  `final` refuses without a
  `creation`, and refuses when the record has not grown since it -- which
  is precisely the "one bundled commit" shape the requirement rules out.
  A second `creation` over further changes is refused, because the
  lifecycle would then name two moments.
* IT STAGES THREE PATHSPECS AND NOTHING ELSE.  Staged work outside them
  is a refusal (a commit publishes the whole index); unstaged work
  outside them is reported and left alone.
* THE NEGATION IS LOAD-BEARING AND IT IS CHECKED.  With .gitignore's
  terminal `!/playthrough/**` removed, `git add` skips the engine's own
  `#<name>.sav` and exits 0 -- so the checkpoint asks git for the save
  BY NAME afterwards, and this suite proves that catch works.
* MACHINE-LOCAL FILES ARE REFUSED, for the same reason: inside that one
  tree the repository's ignores do not apply, so __pycache__, a *.pyc, an
  ad-hoc test file and a quarantined film are all committable and none of
  them is evidence.
* THE EVIDENCE IS COUNTED, NOT TRUSTED.  Frames, rows and observation
  rows must agree; the save must be one world and one survivor; the
  engine's own record of what it loaded must match the save on disk; a
  keybindings file naming a debug action is a refusal.
* A RE-RUN IS SAFE.  Nothing pending means exit 0, COMMITTED=no, and no
  empty commit manufactured to make the run look eventful.

HOW A COMMIT LIFECYCLE IS TESTED WITHOUT TOUCHING THE REAL HISTORY
Every test builds a whole miniature checkout -- data/, src/, .gitignore
with the real negation, a save tree, frames, a manifest, an observation
sidecar -- inside a temporary directory, runs `git init` there, and runs
the REAL commit_artifacts.sh against it.  env.sh and manifest.py resolve
their trees from their own file location, so copying them into the
sandbox points the entire artifact layout at the sandbox and nothing can
reach the committed artifacts.  The sandbox lives under a PRIVATE base
rather than /tmp for the same reason test_embed_captions.py does: env.sh
verifies the ownership and writability of every tool it resolves and of
every directory above it, and /tmp on this host is mode 2777.

The identity comes from GIT_AUTHOR_* / GIT_COMMITTER_* in the sandbox's
environment, set to the same identity the platform supplies, with
GIT_CONFIG_GLOBAL=/dev/null and GIT_CONFIG_NOSYSTEM=1 so the host's own
configuration cannot make a test pass.  That is also how the missing
identity case is produced: drop those four variables and git has nothing
to resolve.

Standard library only.  Nothing outside the temporary directory is
written.
"""

import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True

TOOLING = os.path.dirname(os.path.abspath(__file__))
SCRIPT_NAME = "commit_artifacts.sh"

# The exit codes commit_artifacts.sh documents, restated here so a
# renumbering has to be deliberate in two places.
EX_OK = 0
EX_USAGE = 1
EX_REPO = 2
EX_IDENTITY = 3
EX_SCOPE = 4
EX_EVIDENCE = 5
EX_LIFECYCLE = 6
EX_COMMIT = 7
EX_PREREQ = 8

# The identity every sandbox commits under: the same one the platform
# supplies, so nothing here depends on a name this suite invented.
AUTHOR_NAME = "Blitzy Agent"
AUTHOR_EMAIL = "agent@blitzy.com"
AUTHOR = "%s <%s>" % (AUTHOR_NAME, AUTHOR_EMAIL)

# The survivor the sandbox saves belong to, and her save's basename.
# The engine encodes a character name with base64 whose last two
# alphabet characters are '+' and '-' (src/catacharset.cpp:215), and the
# checkpoint holds lastworld.json against exactly that spelling.
WORLD = "Fern Creek"
CHARACTER = "Delphine Ouellette"
SAVE_BASENAME = "#RGVscGhpbmUgT3VlbGxldHRl.sav"

# The three patterns that make the negation load-bearing, reproduced
# from the repository's own .gitignore, plus the terminal negation that
# rescues the tree from them.
SANDBOX_GITIGNORE = """\
# Reproduced from the repository's own rules, because these three are
# what make the terminal negation below load-bearing.
*.log
debug.log
\\#*
obj
# The negation the save data depends on.  LAST, because git applies the
# last matching pattern.
!/playthrough/**
"""

NEGATION_LINE = "!/playthrough/**"

SANDBOX_GITATTRIBUTES = "* text=auto\n*.sav binary\n*.gsav binary\n"

REAL_TOOLS = (
    "bash", "git", "awk", "grep", "mkdir", "mv", "rm", "wc", "tail",
    "head", "dirname", "basename", "cat", "env", "chmod", "cp", "ls",
    "tr", "sed", "sort", "readlink", "printf", "touch", "python3",
    "date", "find",
    # stat is how env.sh verifies the runtime directory; id answers for
    # the owner when $EUID is not exported; realpath and flock belong to
    # the confinement and locking machinery.
    "stat", "id", "realpath", "flock", "cut", "sleep", "mktemp",
    "sha256sum", "uname",
)


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
    nothing about the lifecycle.  /tmp cannot serve on this host, which
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
    "would test the prerequisite failure instead of the lifecycle.  "
    "Set $PLAYTHROUGH_TEST_TMPDIR to a directory owned by this user "
    "with no group or world write bit on it or on any of its parents.")


def _interpreter():
    """The interpreter env.sh should be pointed at.

    env.sh warns when the resolved interpreter is not the CPython 3.12
    requirements.lock pins its wheels for, and a suite that provoked
    that warning on every run would teach a reader to ignore it.
    """
    provisioned = "/opt/playthrough-venv/bin/python"
    if os.path.isfile(provisioned) and os.access(provisioned, os.X_OK):
        return provisioned
    return sys.executable


INTERPRETER = _interpreter()


class CheckpointFixture(unittest.TestCase):
    """A miniature checkout, a real git repository, and one run."""

    # The evidence the fixture starts with: enough frames for a
    # creation checkpoint, and a manifest and sidecar that match.
    CREATION_ROWS = 4
    # What gameplay adds before the final checkpoint.
    SESSION_ROWS = 3

    def setUp(self):
        if SANDBOX_BASE is None:
            self.skipTest(NO_SANDBOX_BASE)
        self.root = tempfile.mkdtemp(prefix="blitzy_checkpoint_",
                                     dir=SANDBOX_BASE)
        self.addCleanup(shutil.rmtree, self.root, True)
        self.checkout = os.path.join(self.root, "checkout")
        self.tooling = os.path.join(self.checkout, "playthrough",
                                    "tooling")
        os.makedirs(self.tooling)
        os.makedirs(os.path.join(self.checkout, "data"))
        os.makedirs(os.path.join(self.checkout, "src"))
        self.write(os.path.join(self.checkout, "src", "path_info.cpp"),
                   "// a marker, not the engine\n")
        # env.sh and manifest.py both resolve their trees from their own
        # location, so copying them here is what points the whole
        # artifact layout at the sandbox.
        for name in ("env.sh", SCRIPT_NAME, "manifest.py"):
            shutil.copyfile(os.path.join(TOOLING, name),
                            os.path.join(self.tooling, name))
        self.script = os.path.join(self.tooling, SCRIPT_NAME)
        os.chmod(self.script, 0o755)
        self.dir = os.path.join(self.checkout, "playthrough")
        self.frames_dir = os.path.join(self.dir, "frames")
        self.build_dir = os.path.join(self.dir, "build")
        os.makedirs(self.frames_dir)
        os.makedirs(self.build_dir)
        self.manifest = os.path.join(self.dir, "manifest.jsonl")
        self.observations = os.path.join(self.build_dir,
                                         "observations.jsonl")
        self.gitignore = os.path.join(self.checkout, ".gitignore")
        self.write(self.gitignore, SANDBOX_GITIGNORE)
        self.write(os.path.join(self.checkout, ".gitattributes"),
                   SANDBOX_GITATTRIBUTES)
        self.write(os.path.join(self.dir, "dossier.md"),
                   "# %s\n\nWritten before play.\n" % CHARACTER)
        self.world_dir = os.path.join(self.dir, "userdir", "save", WORLD)
        self.config_dir = os.path.join(self.dir, "userdir", "config")
        self.save_file = os.path.join(self.world_dir, SAVE_BASENAME)
        self.master = os.path.join(self.world_dir, "master.gsav")
        self.lastworld = os.path.join(self.config_dir, "lastworld.json")
        self.bin = os.path.join(self.root, "bin")
        os.makedirs(self.bin)
        self.link_real_tools()
        self.init_repository()

    # -- fixture plumbing --------------------------------------------

    def write(self, path, text, mode=None):
        """Write a file, creating its parent, and return the path.

        AN EXISTING SYMLINK IS REPLACED, NEVER WRITTEN THROUGH: this
        fixture puts symlinks to real system tools on a private PATH, and
        opening such a name for writing would truncate the HOST's binary.
        """
        parent = os.path.dirname(path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)
        if os.path.islink(path):
            os.unlink(path)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        if mode is not None:
            os.chmod(path, mode)
        return path

    def link_real_tools(self):
        """Symlink the genuine tools the script and env.sh need."""
        for tool in REAL_TOOLS:
            resolved = shutil.which(tool)
            link = os.path.join(self.bin, tool)
            if resolved and not os.path.exists(link):
                os.symlink(resolved, link)

    def row(self, index):
        """One manifest row: honest, in voice, and clock-free.

        `ingame_clock` is null on every row, which is a real and
        legitimate reading -- a menu frame, or a survivor with no watch
        in hand -- and it keeps this suite's subject the LIFECYCLE
        rather than the clock-honesty gate, which has its own coverage
        in test_manifest.py.
        """
        return {
            "frame": index,
            "file": "playthrough/frames/frame_%05d.png" % index,
            "real_ts": "2026-08-04T06:53:%02d.429Z" % (index % 60),
            "ingame_clock": None,
            "action": "press 'j' -- step south along the passage",
            "commentary": ("The door at the end is shut and I would "
                           "rather know what is behind it than stand "
                           "here wondering."),
        }

    def observation(self, index):
        """The sidecar row session.py writes beside each capture."""
        return {
            "frame": index,
            "file": "playthrough/frames/frame_%05d.png" % index,
            "clock_status": "unreadable",
            "key": "j",
        }

    def write_evidence(self, count):
        """Write `count` frames, rows and observation rows."""
        for index in range(1, count + 1):
            self.write(
                os.path.join(self.frames_dir,
                             "frame_%05d.png" % index),
                "not a real png, but a real file\n")
        with open(self.manifest, "w", encoding="utf-8") as handle:
            for index in range(1, count + 1):
                handle.write(json.dumps(self.row(index)) + "\n")
        with open(self.observations, "w", encoding="utf-8") as handle:
            for index in range(1, count + 1):
                handle.write(
                    json.dumps(self.observation(index)) + "\n")
        return count

    def write_save(self):
        """The engine-managed state a checkpoint records."""
        self.write(self.master, "master state\n")
        self.write(self.save_file, "character state\n")
        self.write(self.lastworld,
                   json.dumps({"world_name": WORLD,
                               "character_name": CHARACTER},
                              indent=2) + "\n")

    def git(self, *args, identity=True, check=True):
        """Run git in the sandbox, hermetically."""
        env = {
            "PATH": self.bin,
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
        }
        if identity:
            env.update(self.identity_environment())
        result = subprocess.run(
            [os.path.join(self.bin, "git")] + list(args),
            cwd=self.checkout, env=env, capture_output=True,
            timeout=120)
        if check and result.returncode != 0:
            raise AssertionError(
                "git %s failed (%d): %s"
                % (" ".join(args), result.returncode,
                   result.stderr.decode("utf-8", "replace")))
        return result.stdout.decode("utf-8", "replace")

    def identity_environment(self):
        """The four variables that give the sandbox an identity.

        NOT `git config`.  The subject of this suite is a script that
        must never write user.name or user.email, and a fixture that
        wrote them into the sandbox's configuration would be modelling
        the thing being ruled out.  These four are the mechanism git
        itself documents for supplying an identity without configuring a
        repository, which is exactly the platform's own arrangement.
        """
        return {
            "GIT_AUTHOR_NAME": AUTHOR_NAME,
            "GIT_AUTHOR_EMAIL": AUTHOR_EMAIL,
            "GIT_COMMITTER_NAME": AUTHOR_NAME,
            "GIT_COMMITTER_EMAIL": AUTHOR_EMAIL,
        }

    def init_repository(self):
        """A repository whose first commit predates the session.

        The tooling, the ignore rules and the dossier are committed
        BEFORE any evidence exists, which is the real order: the code
        lands, the survivor is written down, and only then is anything
        captured.  It also means a `creation` checkpoint has something
        to record.
        """
        self.git("init", "--quiet", "-b", "main", ".")
        self.git("add", "-A", "--", ".gitignore", ".gitattributes",
                 "playthrough")
        self.git("commit", "--quiet", "-m",
                 "Land the pipeline and write the survivor down")

    # -- running the subject -----------------------------------------

    def run_script(self, args=(), identity=True, **environment):
        """Run the real commit_artifacts.sh in the sandbox."""
        env = {
            "PATH": self.bin,
            # THE PLATFORM GATE IS SATISFIED, NOT SWITCHED OFF.  The
            # waiver takes a reason, which is what makes declaring it in
            # a fixture honest; the gate has its own coverage in
            # test_env.py and the production path is unaffected.
            "PLAYTHROUGH_ALLOW_EOL_PLATFORM":
                "test fixture; the platform gate has its own coverage "
                "in test_env.py",
            "PLAYTHROUGH_PYTHON": INTERPRETER,
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
        }
        if identity:
            env.update(self.identity_environment())
        for name, value in environment.items():
            if value is None:
                env.pop(name, None)
            else:
                env[name] = str(value)
        command = ["/usr/bin/env", "-i"]
        command.extend("%s=%s" % item for item in env.items())
        command.extend(["/bin/bash", "--noprofile", "--norc",
                        self.script])
        command.extend(args)
        result = subprocess.run(command, cwd=self.checkout,
                                capture_output=True, timeout=300)
        return (result.returncode,
                result.stdout.decode("utf-8", "replace"),
                result.stderr.decode("utf-8", "replace"))

    def payload(self, out):
        """Parse the KEY=value contract off stdout."""
        fields = {}
        for line in out.splitlines():
            if not line:
                continue
            self.assertIn("=", line,
                          msg="stdout carries KEY=value only: %r" % line)
            key, _, value = line.partition("=")
            fields[key] = value
        return fields

    def checkpoint(self, name, **environment):
        """Run a checkpoint that is expected to succeed."""
        status, out, err = self.run_script((name,), **environment)
        self.assertEqual(
            status, EX_OK,
            msg="the '%s' checkpoint failed (%d):\n%s"
                % (name, status, err))
        return self.payload(out), err

    def refuse(self, code, args=(), **environment):
        """Run a checkpoint expected to be refused, and prove it was.

        A REFUSAL MAY NOT COMMIT AND MAY NOT LEAVE THE INDEX DIRTY.
        Asserting both here rather than in each test is what makes it
        impossible to add a refusal test that forgets to check them.
        """
        before = self.head()
        status, out, err = self.run_script(args, **environment)
        self.assertEqual(
            status, code,
            msg="expected exit %d, got %d:\n%s" % (code, status, err))
        self.assertEqual(
            before, self.head(),
            msg="a refused checkpoint moved HEAD")
        return err + out

    # -- reading the repository back ---------------------------------

    def head(self):
        """The current commit, or an empty string before the first."""
        result = subprocess.run(
            [os.path.join(self.bin, "git"), "rev-parse", "--verify",
             "--quiet", "HEAD"],
            cwd=self.checkout, capture_output=True,
            env={"PATH": self.bin, "GIT_CONFIG_GLOBAL": "/dev/null",
                 "GIT_CONFIG_NOSYSTEM": "1"},
            timeout=60)
        return result.stdout.decode("utf-8", "replace").strip()

    def log_subjects(self):
        """Every commit subject, newest first."""
        return self.git("log", "--format=%s", identity=False).split("\n")

    def message(self, revision="HEAD"):
        """One commit's whole message."""
        return self.git("log", "-1", "--format=%B", revision,
                        identity=False)

    def tracked(self, pathspec):
        """The paths git has in the index under `pathspec`."""
        listing = self.git("ls-files", "--", pathspec, identity=False)
        return [line for line in listing.split("\n") if line]

    def is_tracked(self, path):
        """True when one exact path is in the index."""
        result = subprocess.run(
            [os.path.join(self.bin, "git"), "ls-files",
             "--error-unmatch", "--", path],
            cwd=self.checkout, capture_output=True,
            env={"PATH": self.bin, "GIT_CONFIG_GLOBAL": "/dev/null",
                 "GIT_CONFIG_NOSYSTEM": "1"},
            timeout=60)
        return result.returncode == 0

    def git_config_text(self):
        """The sandbox's own configuration file, read as a file.

        Deliberately NOT `git config --get user.name`.  What is being
        asserted is that a particular command was never run at all, and
        reading the file it would have written is the form of that
        assertion which cannot be confused with running it.
        """
        path = os.path.join(self.checkout, ".git", "config")
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()

    # -- the whole lifecycle, for tests that need it in place --------

    def take_creation(self):
        """Write the creation evidence and take the first checkpoint."""
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        return self.checkpoint("creation")

    def play_session(self):
        """Grow the record the way gameplay grows it."""
        return self.write_evidence(
            self.CREATION_ROWS + self.SESSION_ROWS)


class TestItNeverWritesGitConfiguration(CheckpointFixture):
    """The single constraint the whole design turns on.

    The identity a commit is made under belongs to the platform.  A
    script that configures it around a missing one hides the very thing
    that needs fixing, and on a host whose rule is that commits carry one
    fixed identity, writing another into the repository is a violation
    rather than a convenience.
    """

    FORBIDDEN = ("config user.name", "config user.email",
                 "config --local user", "config --global user")

    def test_the_source_contains_no_identity_write(self):
        with open(os.path.join(TOOLING, SCRIPT_NAME),
                  encoding="utf-8") as handle:
            source = handle.read()
        for fragment in self.FORBIDDEN:
            self.assertNotIn(
                fragment, source,
                msg=("commit_artifacts.sh must never write an identity; "
                     "found %r in its source" % fragment))

    def test_the_source_invokes_git_config_nowhere(self):
        """Not even a read.

        A read is harmless in itself, but `git config` is the command
        this script is defined by not running, and a source that
        contains it for any purpose is one where the next edit adds an
        argument.  `git var` answers the only question there is, and it
        answers it with the same resolution order the commit will use.
        """
        pattern = re.compile(r"(?:\bgit\b|GIT\}\")\s+config\b")
        with open(os.path.join(TOOLING, SCRIPT_NAME),
                  encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                if line.lstrip().startswith("#"):
                    continue
                self.assertIsNone(
                    pattern.search(line),
                    msg=("line %d invokes git config: %r"
                         % (number, line.rstrip())))

    def test_a_whole_lifecycle_leaves_the_configuration_alone(self):
        before = self.git_config_text()
        self.take_creation()
        self.play_session()
        self.checkpoint("final")
        after = self.git_config_text()
        self.assertEqual(
            before, after,
            msg="the repository's configuration was modified")
        self.assertNotIn("user", after.replace("[core]", ""))

    def test_the_identity_asked_for_is_the_identity_recorded(self):
        fields, _ = self.take_creation()
        self.assertEqual(fields["AUTHOR"], AUTHOR)
        self.assertEqual(
            self.git("log", "-1", "--format=%an <%ae>",
                     identity=False).strip(), AUTHOR)
        self.assertEqual(
            self.git("log", "-1", "--format=%cn <%ce>",
                     identity=False).strip(), AUTHOR)


class TestTheIdentityGate(CheckpointFixture):
    """An identity that does not resolve is a refusal."""

    def test_no_identity_anywhere_is_refused(self):
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        message = self.refuse(EX_IDENTITY, ("creation",),
                              identity=False)
        self.assertIn("cannot determine who", message)
        self.assertIn("WILL NOT SET user.name", message)

    def test_the_refusal_names_the_environment_remedy(self):
        """The remedy has to be the platform, not the repository.

        A message that said "run git config" would be telling the
        operator to do the thing this script refuses to do.
        """
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        message = self.refuse(EX_IDENTITY, ("creation",),
                              identity=False)
        self.assertIn("GIT_AUTHOR_NAME", message)
        self.assertIn("GIT_COMMITTER_EMAIL", message)

    def test_nothing_is_staged_by_an_identity_refusal(self):
        """The gate runs BEFORE the index is touched."""
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        self.refuse(EX_IDENTITY, ("creation",), identity=False)
        self.assertEqual(
            "", self.git("diff", "--cached", "--name-only",
                         identity=False).strip())

    def test_a_split_attribution_is_refused(self):
        """Author and committer must be the same person.

        The history is part of this evidence and a commit made by two
        identities is a question nobody can answer afterwards.  It is
        also invisible in `git log` without a format string, which is
        what makes it worth a gate.
        """
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        message = self.refuse(
            EX_IDENTITY, ("creation",),
            GIT_COMMITTER_NAME="Someone Else",
            GIT_COMMITTER_EMAIL="someone@example.invalid")
        self.assertIn("the author would be", message)
        self.assertIn("Someone Else", message)

    def test_an_identity_with_no_address_is_refused(self):
        """git resolves it; this rejects it as unusable.

        An empty GIT_AUTHOR_EMAIL makes git produce `Name <>`, which is a
        successful resolution of an identity that identifies nobody.
        """
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        message = self.refuse(EX_IDENTITY, ("creation",),
                              GIT_AUTHOR_EMAIL="",
                              GIT_COMMITTER_EMAIL="")
        self.assertIn("angle brackets", message)

    def test_status_reports_a_missing_identity_without_refusing(self):
        """`status` is run precisely when something is wrong."""
        status, out, err = self.run_script(("status",), identity=False)
        self.assertEqual(status, EX_OK, msg=err)
        self.assertIn("cannot determine an author identity", err)
        self.assertEqual(self.payload(out)["AUTHOR"], "")


class TestTheRepositoryGate(CheckpointFixture):
    """The right repository, a real branch, and nothing half-done."""

    def test_a_detached_head_is_refused(self):
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        self.git("checkout", "--quiet", "--detach", "HEAD")
        message = self.refuse(EX_REPO, ("creation",))
        self.assertIn("HEAD is detached", message)
        self.assertIn("belong to no branch", message)

    def test_an_operation_in_progress_is_refused(self):
        """A half-finished rebase or merge owns the index.

        Staging into it would either fail confusingly or conclude
        somebody else's operation with this checkpoint's message.
        """
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        self.write(os.path.join(self.checkout, ".git", "MERGE_HEAD"),
                   self.head() + "\n")
        message = self.refuse(EX_REPO, ("creation",))
        self.assertIn("git operation is in progress", message)
        self.assertIn("MERGE_HEAD", message)

    def test_every_in_progress_marker_is_covered(self):
        """One marker per operation git can be halfway through."""
        markers = ("rebase-merge", "rebase-apply", "MERGE_HEAD",
                   "CHERRY_PICK_HEAD", "REVERT_HEAD", "BISECT_LOG")
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        for marker in markers:
            path = os.path.join(self.checkout, ".git", marker)
            with self.subTest(marker=marker):
                if marker.startswith("rebase-"):
                    os.makedirs(path)
                else:
                    self.write(path, "x\n")
                message = self.refuse(EX_REPO, ("creation",))
                self.assertIn(marker, message)
                if marker.startswith("rebase-"):
                    shutil.rmtree(path)
                else:
                    os.unlink(path)

    def test_a_tree_with_no_history_is_refused(self):
        """A checkpoint records a position in a history, not a first."""
        fresh = os.path.join(self.root, "fresh")
        shutil.copytree(self.checkout, fresh, symlinks=True)
        shutil.rmtree(os.path.join(fresh, ".git"))
        subprocess.run(
            [os.path.join(self.bin, "git"), "init", "--quiet", "-b",
             "main", "."],
            cwd=fresh, capture_output=True,
            env={"PATH": self.bin, "GIT_CONFIG_GLOBAL": "/dev/null",
                 "GIT_CONFIG_NOSYSTEM": "1"}, timeout=120, check=True)
        self.checkout = fresh
        self.script = os.path.join(fresh, "playthrough", "tooling",
                                   SCRIPT_NAME)
        self.dir = os.path.join(fresh, "playthrough")
        message = self.refuse(EX_REPO, ("creation",))
        self.assertIn("no commit yet", message)


class TestTheScopeGate(CheckpointFixture):
    """Three pathspecs, and a commit publishes the whole index."""

    def test_staged_work_outside_the_feature_is_refused(self):
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        self.write(os.path.join(self.checkout, "src", "other.cpp"),
                   "// somebody else's change\n")
        self.git("add", "--", "src/other.cpp")
        message = self.refuse(EX_SCOPE, ("creation",))
        self.assertIn("outside this feature", message)
        self.assertIn("src/other.cpp", message)
        self.assertIn("publishes the whole index", message)

    def test_unstaged_work_outside_the_feature_is_only_reported(self):
        """It cannot ride along, so it is not an obstacle.

        `git add` is given pathspecs and cannot reach past them, so an
        untracked or merely modified file elsewhere is somebody else's
        business.  Refusing over it would make this step unusable in a
        working checkout; saying nothing would let an operator believe it
        had been committed.
        """
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        self.write(os.path.join(self.checkout, "src", "other.cpp"),
                   "// somebody else's change\n")
        fields, err = self.checkpoint("creation")
        self.assertEqual(fields["COMMITTED"], "yes")
        self.assertIn("exactly as found", err)
        self.assertIn("src/other.cpp", err)
        self.assertFalse(self.is_tracked("src/other.cpp"))

    def test_the_commit_holds_only_the_three_pathspecs(self):
        self.write(os.path.join(self.checkout, "src", "other.cpp"),
                   "// somebody else's change\n")
        self.take_creation()
        changed = self.git("show", "--name-only", "--format=", "HEAD",
                           identity=False).split("\n")
        for path in [line for line in changed if line]:
            with self.subTest(path=path):
                self.assertTrue(
                    path in (".gitignore", ".gitattributes") or
                    path.startswith("playthrough/"),
                    msg="%r is outside the three pathspecs" % path)


class TestTheHygieneGate(CheckpointFixture):
    """What the terminal negation re-includes, and must not archive.

    Everywhere else in this repository __pycache__ and *.pyc are ignored.
    Inside playthrough/ the negation makes them committable, and a
    checkpoint that archived them would have to be undone by hand.
    """

    def refuse_over(self, relative, directory=False):
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        path = os.path.join(self.dir, relative)
        if directory:
            os.makedirs(path)
        else:
            self.write(path, "derived, not evidence\n")
        message = self.refuse(EX_SCOPE, ("creation",))
        self.assertIn("machine-local files", message)
        return message

    def test_bytecode_from_a_test_run_is_refused(self):
        message = self.refuse_over(os.path.join("tooling",
                                                "__pycache__"),
                                   directory=True)
        self.assertIn("__pycache__", message)
        self.assertIn("python -B", message)

    def test_a_compiled_module_is_refused(self):
        message = self.refuse_over(
            os.path.join("tooling", "manifest.cpython-312.pyc"))
        self.assertIn(".pyc", message)

    def test_an_adhoc_validation_file_is_refused(self):
        message = self.refuse_over("blitzy_adhoc_test_probe.py")
        self.assertIn("blitzy_adhoc_test_probe.py", message)

    def test_a_quarantined_film_is_refused(self):
        """embed_captions.sh leaves it beside the published one.

        It is evidence of a failure and worth keeping, but it belongs
        OUTSIDE a tree whose ignores do not apply, and the refusal says
        so.
        """
        message = self.refuse_over(".cata-play-cc.rejected.mp4")
        self.assertIn("rejected.mp4", message)
        self.assertIn("OUTSIDE", message)

    def test_a_retained_previous_film_is_refused(self):
        message = self.refuse_over(".cata-play-cc.previous.mp4")
        self.assertIn("previous.mp4", message)

    def test_a_clean_tree_passes(self):
        self.take_creation()
        self.assertEqual(
            [], [path for path in self.tracked("playthrough")
                 if "__pycache__" in path or path.endswith(".pyc")])


class TestTheSaveGate(CheckpointFixture):
    """One world, one survivor, and the engine agreeing with both."""

    def test_a_missing_save_tree_is_refused(self):
        self.write_evidence(self.CREATION_ROWS)
        message = self.refuse(EX_EVIDENCE, ("creation",))
        self.assertIn("no save tree", message)

    def test_a_second_world_is_refused(self):
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        os.makedirs(os.path.join(self.dir, "userdir", "save",
                                 "Somewhere Else"))
        message = self.refuse(EX_EVIDENCE, ("creation",))
        self.assertIn("world director", message)
        self.assertIn("second run", message)

    def test_a_world_with_no_master_save_is_refused(self):
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        os.unlink(self.master)
        message = self.refuse(EX_EVIDENCE, ("creation",))
        self.assertIn("master.gsav", message)

    def test_a_second_survivor_is_refused(self):
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        self.write(os.path.join(self.world_dir, "#U29tZWJvZHk.sav"),
                   "another character\n")
        message = self.refuse(EX_EVIDENCE, ("creation",))
        self.assertIn("character save", message)
        self.assertIn("one unique survivor", message)

    def test_a_missing_lastworld_record_is_refused(self):
        """Which survivor was loaded has to come from the engine.

        lastworld.json appears the moment a world is loaded, so its
        absence means the session never got that far -- and without it
        the save on disk cannot be tied to anything that was played.
        """
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        os.unlink(self.lastworld)
        message = self.refuse(EX_EVIDENCE, ("creation",))
        self.assertIn("lastworld.json", message)

    def test_an_unreadable_lastworld_record_is_refused(self):
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        self.write(self.lastworld, "{not json at all\n")
        message = self.refuse(EX_EVIDENCE, ("creation",))
        self.assertIn("could not be", message)
        self.assertIn("refusal here, not a skipped one", message)

    def test_a_world_disagreement_is_refused(self):
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        self.write(self.lastworld,
                   json.dumps({"world_name": "Somewhere Else",
                               "character_name": CHARACTER}) + "\n")
        message = self.refuse(EX_EVIDENCE, ("creation",))
        self.assertIn("Somewhere Else", message)
        self.assertIn("different worlds", message)

    def test_a_character_disagreement_is_refused(self):
        """The base64 spelling is the check.

        The engine encodes the name with '+' and '-' as the last two
        alphabet characters, so the decoded name in lastworld.json and
        the encoded name of the save file are two spellings of one fact
        and can be held against each other.
        """
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        self.write(self.lastworld,
                   json.dumps({"world_name": WORLD,
                               "character_name": "Someone Else"}) + "\n")
        message = self.refuse(EX_EVIDENCE, ("creation",))
        self.assertIn("Someone Else", message)
        self.assertIn("which survivor", message)

    def test_the_survivor_is_reported_from_the_engine_record(self):
        fields, _ = self.take_creation()
        self.assertEqual(fields["WORLD"], WORLD)
        self.assertEqual(fields["CHARACTER"], CHARACTER)


class TestTheEvidenceGate(CheckpointFixture):
    """One keystroke, one capture, one row, one observation."""

    def test_an_absent_record_is_refused(self):
        self.write_save()
        message = self.refuse(EX_EVIDENCE, ("creation",))
        self.assertIn("no record at", message)

    def test_a_capture_with_no_row_is_refused(self):
        """The direction manifest.py's own check cannot see.

        `manifest.py verify --require-frames` holds every ROW to a
        capture.  An extra capture that no row accounts for passes that
        and still breaks the invariant, so the counts are compared here.
        """
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        self.write(
            os.path.join(self.frames_dir, "frame_%05d.png"
                         % (self.CREATION_ROWS + 1)),
            "an orphan capture\n")
        message = self.refuse(EX_EVIDENCE, ("creation",))
        self.assertIn("capture with no row", message)

    def test_a_row_with_no_capture_is_refused(self):
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        os.unlink(os.path.join(self.frames_dir, "frame_00002.png"))
        message = self.refuse(EX_EVIDENCE, ("creation",))
        self.assertIn("manifest.py refused", message)
        self.assertIn("no capture on disk for frame 2", message)

    def test_the_refusal_says_re_record_rather_than_edit(self):
        """The record is append-only and that is the whole point.

        A gate whose remedy was "fix the row" would be inviting the one
        thing the requirement forbids.
        """
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        os.unlink(os.path.join(self.frames_dir, "frame_00002.png"))
        message = self.refuse(EX_EVIDENCE, ("creation",))
        self.assertIn("RE-RECORDING", message)
        self.assertIn("never by editing", message)

    def test_a_missing_observation_sidecar_is_refused(self):
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        os.unlink(self.observations)
        message = self.refuse(EX_EVIDENCE, ("creation",))
        self.assertIn("observation sidecar", message)

    def test_a_short_observation_sidecar_is_refused(self):
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        with open(self.observations, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(self.observation(1)) + "\n")
        message = self.refuse(EX_EVIDENCE, ("creation",))
        self.assertIn("1 row(s) against the manifest's 4", message)

    def test_a_record_that_fails_its_own_gate_is_refused(self):
        """A voice violation stops the checkpoint, not just the film.

        The sentence would go verbatim into the transcript and onto the
        film, so a checkpoint that committed it would be preserving the
        defect as evidence.
        """
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        rows = [self.row(index)
                for index in range(1, self.CREATION_ROWS + 1)]
        rows[-1]["commentary"] = ("The game drew the sidebar wrong "
                                  "again.")
        with open(self.manifest, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")
        message = self.refuse(EX_EVIDENCE, ("creation",))
        self.assertIn("manifest.py refused", message)
        self.assertIn("survivor's own voice", message)

    def test_the_counts_are_reported(self):
        fields, _ = self.take_creation()
        self.assertEqual(fields["FRAMES"], str(self.CREATION_ROWS))
        self.assertEqual(fields["ROWS"], str(self.CREATION_ROWS))


class TestTheNoCheatingGate(CheckpointFixture):
    """A committed artifact carries the claim, so it is checkable."""

    def test_a_bound_debug_action_is_refused(self):
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        self.write(
            os.path.join(self.config_dir, "keybindings.json"),
            json.dumps({"keybindings": [
                {"id": "debug_mode", "category": "DEFAULTMODE",
                 "bindings": [{"input_method": "keyboard_char",
                               "key": "Z"}]}]}, indent=2) + "\n")
        message = self.refuse(EX_EVIDENCE, ("creation",))
        self.assertIn("debug action", message)
        self.assertIn("ship unbound", message)

    def test_each_debug_action_is_covered(self):
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        path = os.path.join(self.config_dir, "keybindings.json")
        for action in ("debug", "debug_mode", "debug_hour_timer"):
            with self.subTest(action=action):
                self.write(path, json.dumps(
                    {"keybindings": [{"id": action}]}) + "\n")
                self.refuse(EX_EVIDENCE, ("creation",))
        os.unlink(path)

    def test_an_ordinary_keybindings_file_passes(self):
        """Only the debug actions matter.

        A survivor may legitimately rebind movement, and a gate that
        refused any keybindings file at all would be refusing ordinary
        play rather than cheating.
        """
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        self.write(
            os.path.join(self.config_dir, "keybindings.json"),
            json.dumps({"keybindings": [
                {"id": "move_south", "category": "DEFAULTMODE",
                 "bindings": [{"input_method": "keyboard_char",
                               "key": "j"}]}]}, indent=2) + "\n")
        fields, _ = self.checkpoint("creation")
        self.assertEqual(fields["COMMITTED"], "yes")

    def test_the_absent_file_is_reported_as_the_evidence(self):
        """The engine writes one only when a binding is changed.

        Its absence is therefore the strongest form of the claim, not a
        gap in it, and the log says so rather than staying quiet.
        """
        _, err = self.take_creation()
        self.assertIn("only when a binding is changed", err)
        self.assertIn("unbound", err)


class TestTheLifecycle(CheckpointFixture):
    """Two commits, in order, with the session between them."""

    def test_final_without_creation_is_refused(self):
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        message = self.refuse(EX_LIFECYCLE, ("final",))
        self.assertIn("no 'creation' checkpoint", message)
        self.assertIn("single bundled commit", message)

    def test_final_over_an_unchanged_record_is_refused(self):
        """The exact shape the requirement rules out.

        A `final` taken with nothing played since `creation` is two
        commits describing one moment, which is the bundled commit with
        an extra step.
        """
        self.take_creation()
        self.write(os.path.join(self.dir, "TECHNICAL_NOTES.md"),
                   "Something changed, but not the record.\n")
        message = self.refuse(EX_LIFECYCLE, ("final",))
        self.assertIn("nothing was played between", message)

    def test_final_after_a_played_session_is_taken(self):
        self.take_creation()
        self.play_session()
        fields, err = self.checkpoint("final")
        self.assertEqual(fields["COMMITTED"], "yes")
        self.assertEqual(
            fields["ROWS"],
            str(self.CREATION_ROWS + self.SESSION_ROWS))
        self.assertIn("grew from 4 to 7", err)

    def test_the_two_commits_are_distinct_and_ordered(self):
        creation, _ = self.take_creation()
        self.play_session()
        final, _ = self.checkpoint("final")
        self.assertNotEqual(creation["COMMIT"], final["COMMIT"])
        self.assertEqual(final["CREATION"], creation["COMMIT"])
        ancestry = self.git("rev-list", "--ancestry-path",
                            "%s..%s" % (creation["COMMIT"],
                                        final["COMMIT"]),
                            identity=False)
        self.assertIn(final["COMMIT"], ancestry)

    def test_a_second_creation_over_new_work_is_refused(self):
        """The trailer would then match two commits.

        `final` finds the creation checkpoint by searching for the
        trailer, so a second one makes the lifecycle stop naming a single
        moment.
        """
        self.take_creation()
        self.play_session()
        message = self.refuse(EX_LIFECYCLE, ("creation",))
        self.assertIn("already exists", message)
        self.assertIn("two commits", message)

    def test_a_re_run_with_nothing_pending_commits_nothing(self):
        """Re-runnable, and no empty commit manufactured.

        An empty commit per invocation would fill the history with
        checkpoints that record no change and make the trailer search
        ambiguous.
        """
        first, _ = self.take_creation()
        before = self.head()
        fields, err = self.checkpoint("creation")
        self.assertEqual(fields["COMMITTED"], "no")
        self.assertEqual(fields["COMMIT"], "")
        self.assertEqual(fields["CREATION"], first["COMMIT"])
        self.assertEqual(before, self.head())
        self.assertIn("No empty commit was manufactured", err)

    def test_the_trailer_is_what_carries_the_lifecycle(self):
        self.take_creation()
        self.assertIn("Playthrough-Checkpoint: creation",
                      self.message())
        self.play_session()
        self.checkpoint("final")
        self.assertIn("Playthrough-Checkpoint: final", self.message())

    def test_the_trailer_is_matched_as_a_whole_line(self):
        """Prose mentioning it must not be mistaken for it.

        git's --grep anchors ^ and $ at line boundaries within the
        message, which is what makes the search exact.
        """
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        self.write(os.path.join(self.dir, "TECHNICAL_NOTES.md"),
                   "Notes.\n")
        self.git("add", "-A", "--", "playthrough")
        self.git("commit", "--quiet", "-m",
                 "Describe the lifecycle",
                 "-m", "It writes Playthrough-Checkpoint: creation "
                       "into each commit.")
        message = self.refuse(EX_LIFECYCLE, ("final",))
        self.assertIn("no 'creation' checkpoint", message)


class TestTheCommitItself(CheckpointFixture):
    """What is in it, and what is proved about it afterwards."""

    def test_every_artifact_class_is_tracked(self):
        self.take_creation()
        for path in ("playthrough/manifest.jsonl",
                     "playthrough/userdir/save/%s/master.gsav" % WORLD,
                     "playthrough/userdir/save/%s/%s"
                     % (WORLD, SAVE_BASENAME),
                     "playthrough/build/observations.jsonl"):
            with self.subTest(path=path):
                self.assertTrue(self.is_tracked(path),
                                msg="%s is not tracked" % path)

    def test_every_capture_is_tracked(self):
        """No decimation, no sampling, no deduplication."""
        self.take_creation()
        self.assertEqual(len(self.tracked("playthrough/frames")),
                         self.CREATION_ROWS)

    def test_the_negation_failing_is_caught_by_name(self):
        """The failure that hides itself, made loud.

        Without the terminal `!/playthrough/**`, .gitignore's `\\#*` rule
        matches the engine's own character save, `git add` skips it and
        exits 0 -- so every count still tallies and the checkpoint looks
        successful.  The only way to know is to ask git for the file BY
        NAME afterwards, which is what assert_tracked_at_head does.
        """
        self.write(self.gitignore,
                   SANDBOX_GITIGNORE.replace(NEGATION_LINE, ""))
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        status, _, err = self.run_script(("creation",))
        self.assertEqual(status, EX_COMMIT, msg=err)
        self.assertIn("is NOT tracked", err)
        self.assertIn(NEGATION_LINE, err)

    def test_the_body_names_what_was_actually_staged(self):
        """Generated from the index, not written from a template.

        A checkpoint that claimed to carry something not in it would be
        the commit-message version of the defect the transcript gate
        exists to stop.
        """
        self.take_creation()
        body = self.message()
        self.assertIn("- save data", body)
        self.assertIn("- captured frames", body)
        self.assertIn("- manifest and timeline", body)
        self.assertIn("%s / %s" % (WORLD, CHARACTER), body)
        self.assertIn("%d keystroke(s)" % self.CREATION_ROWS, body)

    def test_a_class_that_is_absent_is_not_claimed(self):
        self.take_creation()
        self.assertNotIn("- assembled film", self.message())

    def test_the_film_is_named_when_it_is_there(self):
        self.take_creation()
        self.play_session()
        self.write(os.path.join(self.dir, "cata-play.mp4"),
                   "not a real film, but a real file\n")
        self.checkpoint("final")
        self.assertIn("- assembled film", self.message())

    def test_nothing_in_the_tree_is_left_uncommitted(self):
        self.take_creation()
        self.assertEqual(
            "",
            self.git("status", "--porcelain", "--", ".gitignore",
                     ".gitattributes", "playthrough",
                     identity=False).strip())

    def test_the_subjects_read_as_the_two_moments(self):
        self.take_creation()
        self.play_session()
        self.checkpoint("final")
        subjects = self.log_subjects()
        self.assertIn("Commit the closed session, its final save and "
                      "its artifacts", subjects[0])
        self.assertIn("Commit the survivor's creation and the save it "
                      "produced", subjects[1])


class TestTheStatusReport(CheckpointFixture):
    """Read-only, and it answers the operator's actual question."""

    def test_status_changes_nothing(self):
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        before = self.head()
        status, out, _ = self.run_script(("status",))
        self.assertEqual(status, EX_OK)
        self.assertEqual(before, self.head())
        self.assertEqual(
            "", self.git("diff", "--cached", "--name-only",
                         identity=False).strip())
        self.assertEqual(self.payload(out)["COMMITTED"], "no")

    def test_status_names_the_missing_creation_checkpoint(self):
        status, out, err = self.run_script(("status",))
        self.assertEqual(status, EX_OK)
        self.assertEqual(self.payload(out)["CREATION"], "")
        self.assertIn("'final' would refuse", err)

    def test_status_reports_the_creation_checkpoint_once_taken(self):
        creation, _ = self.take_creation()
        status, out, _ = self.run_script(("status",))
        self.assertEqual(status, EX_OK)
        self.assertEqual(self.payload(out)["CREATION"],
                         creation["COMMIT"])

    def test_status_survives_evidence_that_would_be_refused(self):
        """It exists to be run when something is wrong.

        Every gate that would refuse reports here instead, so an operator
        sees the whole picture in one call rather than discovering the
        gates one refusal at a time.
        """
        self.write_evidence(self.CREATION_ROWS)
        status, out, _ = self.run_script(("status",))
        self.assertEqual(status, EX_OK)
        fields = self.payload(out)
        self.assertEqual(fields["WORLD"], "")
        self.assertEqual(fields["FRAMES"], str(self.CREATION_ROWS))

    def test_status_lists_what_a_checkpoint_would_stage(self):
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        _, _, err = self.run_script(("status",))
        self.assertIn("would stage", err)
        self.assertIn("playthrough/manifest.jsonl", err)


class TestTheUsage(CheckpointFixture):
    """One subcommand, no options, and no default."""

    def test_help_succeeds_and_explains_the_constraint(self):
        """Usage goes to stdout when it was ASKED for.

        The same convention launch_game.sh follows: an explicit `help`
        prints on stdout because it is the answer to the question, while
        a usage error prints on stderr beside the diagnosis.  The
        KEY=value contract governs the subcommands that report a
        checkpoint, which is what a caller parses.
        """
        status, out, _ = self.run_script(("help",))
        self.assertEqual(status, EX_OK)
        self.assertIn("usage:", out)
        for name in ("creation", "final", "status", "help"):
            with self.subTest(subcommand=name):
                self.assertIn(name, out)
        self.assertIn("never writes git configuration", out)
        self.assertIn("configure the platform, not the repository", out)
        self.assertIn("stdout carries KEY=value lines only", out)

    def test_the_help_flags_are_the_same_thing(self):
        for flag in ("-h", "--help"):
            with self.subTest(flag=flag):
                status, out, _ = self.run_script((flag,))
                self.assertEqual(status, EX_OK)
                self.assertIn("usage:", out)

    def test_a_usage_error_explains_itself_on_stderr(self):
        """The error channel carries the diagnosis, not stdout.

        A caller parsing stdout for KEY=value must not be handed a usage
        block instead, so the failing paths print theirs on stderr.
        """
        status, out, err = self.run_script(("commit-everything",))
        self.assertEqual(status, EX_USAGE)
        self.assertEqual("", out)
        self.assertIn("usage:", err)

    def test_no_subcommand_is_a_usage_error(self):
        """There is no default, on purpose.

        The two commits mean different things and taking the wrong one is
        not something a default can be right about.
        """
        message = self.refuse(EX_USAGE)
        self.assertIn("which checkpoint", message)

    def test_an_unknown_subcommand_is_a_usage_error(self):
        message = self.refuse(EX_USAGE, ("commit-everything",))
        self.assertIn("unknown subcommand", message)

    def test_a_second_argument_is_a_usage_error(self):
        message = self.refuse(EX_USAGE, ("creation", "--force"))
        self.assertIn("one subcommand, no options", message)

    def test_stdout_is_key_equals_value_only(self):
        fields, _ = self.take_creation()
        for key in ("CHECKPOINT", "COMMITTED", "COMMIT", "AUTHOR",
                    "WORLD", "CHARACTER", "FRAMES", "ROWS",
                    "CREATION"):
            with self.subTest(key=key):
                self.assertIn(key, fields)


class TestTheSuiteTouchesNothingReal(CheckpointFixture):
    """The committed artifacts and the real history are untouched."""

    def test_the_sandbox_is_where_everything_happened(self):
        self.take_creation()
        self.assertTrue(self.head())
        self.assertTrue(
            os.path.realpath(self.checkout).startswith(
                os.path.realpath(self.root)))

    def test_the_real_tooling_is_only_ever_copied(self):
        original = os.path.join(TOOLING, SCRIPT_NAME)
        with open(original, "rb") as handle:
            before = handle.read()
        self.take_creation()
        with open(original, "rb") as handle:
            self.assertEqual(before, handle.read())

    def test_the_real_repository_has_no_sandbox_commit(self):
        """A belt-and-braces check on the fixture's confinement.

        Every git call this suite makes runs with cwd inside the sandbox,
        and this asserts the consequence rather than the intention.
        """
        creation, _ = self.take_creation()
        result = subprocess.run(
            ["git", "cat-file", "-e", creation["COMMIT"]],
            cwd=TOOLING, capture_output=True, timeout=60)
        self.assertNotEqual(
            result.returncode, 0,
            msg="a sandbox commit exists in the real repository")


if __name__ == "__main__":
    unittest.main(verbosity=2)
