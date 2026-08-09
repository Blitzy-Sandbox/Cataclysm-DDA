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
* IT STAGES playthrough/ AND NOTHING ELSE, BY ARTIFACT CLASS, IN BOUNDED
  BATCHES.  No blanket add appears in the source: no -A, no bare '.', no
  -f, no shell glob.  Staged work outside the tree is a refusal (a commit
  publishes the whole index); unstaged work outside it is reported and
  left alone; .gitignore and .gitattributes are checked here and
  committed elsewhere.  Explicit enumeration is held to being COMPLETE by
  a sweep that refuses a checkpoint leaving anything under playthrough/
  unstaged.
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

import hashlib
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
        self.amendments = os.path.join(self.dir, "amendments.jsonl")
        self.digests = os.path.join(self.build_dir,
                                    "frame_digests.jsonl")
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

    def digest_row(self, index):
        """The attestation session.py appends for one capture.

        Hashed off the file this fixture just wrote, so the ledger is a
        real measurement of real bytes rather than a constant that
        happens to satisfy the gate.  `attested` is "capture", which is
        what the running pipeline records: the fixture's frame IS
        published at the moment it is written.
        """
        path = os.path.join(self.frames_dir, "frame_%05d.png" % index)
        with open(path, "rb") as handle:
            payload = handle.read()
        return {
            "frame": index,
            "file": "playthrough/frames/frame_%05d.png" % index,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload),
            "attested": "capture",
            "attested_ts": "2026-08-04T06:53:%02d.429Z" % (index % 60),
            "git_blob": None,
            "git_commit": None,
        }

    def write_evidence(self, count):
        """Write `count` frames, rows, sidecar rows and attestations."""
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
        self.write_digests(count)
        return count

    def write_digests(self, count):
        """Seal `count` frames into the capture attestation ledger."""
        with open(self.digests, "w", encoding="utf-8") as handle:
            for index in range(1, count + 1):
                handle.write(json.dumps(self.digest_row(index)) + "\n")
        return count

    def write_save(self):
        """The engine-managed state a checkpoint records."""
        self.write(self.master, "master state\n")
        self.write(self.save_file, "character state\n")
        self.write(self.lastworld,
                   json.dumps({"world_name": WORLD,
                               "character_name": CHARACTER},
                              indent=2) + "\n")

    def mark_death_in_record(self):
        """Make the last two captured rows the observed death sequence."""
        with open(self.manifest, "r", encoding="utf-8") as handle:
            rows = [json.loads(line) for line in handle if line.strip()]
        self.assertGreaterEqual(len(rows), 2)
        rows[-2]["action"] = (
            "press 'Return' -- submit Delphine Ouellette's last words: "
            "keep moving")
        rows[-2]["commentary"] = "Leave it there: keep moving."
        rows[-1]["action"] = (
            "press 'Escape' -- exit the post-death scores screen")
        rows[-1]["commentary"] = "Let it end."
        with open(self.manifest, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")

    def write_death_persistence(self, mark_record=True):
        """Replace the live save with the engine's death-generation set."""
        for path in (self.save_file, self.master):
            if os.path.exists(path):
                os.unlink(path)
        generation = os.path.join(
            self.dir, "userdir", "graveyard",
            "2026-08-06T06-53-53")
        grave_save = self.write(
            os.path.join(generation, SAVE_BASENAME),
            json.dumps({
                "debug_mode": False,
                "player": {"name": CHARACTER},
            }) + "\n")
        grave_log = self.write(
            os.path.join(generation, SAVE_BASENAME[:-4] + ".log"),
            "character log\n")
        memorial_base = os.path.join(
            self.dir, "userdir", "memorial", WORLD,
            "%s-2026-08-06-06-53-53" % CHARACTER)
        memorial_json = self.write(
            memorial_base + ".json",
            json.dumps({
                "log": [
                    {"message": "%s was killed." % CHARACTER},
                    {"message": "Last words: keep moving"},
                    {"message": "Died"},
                ],
                "stats": {
                    "data": {
                        "game_avatar_death": {
                            "event_counts": [[{
                                "avatar_name": [
                                    "string", CHARACTER],
                            }, {"count": 1}]],
                        },
                    },
                },
            }) + "\n")
        memorial_text = self.write(
            memorial_base + ".txt",
            "In memory of: %s\nShe died on Year 1, May 20.\n"
            % CHARACTER)
        if mark_record:
            self.mark_death_in_record()
        return (grave_save, grave_log, memorial_json, memorial_text)

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
            # NO PLATFORM WAIVER, DELIBERATELY.  This fixture used to
            # set PLAYTHROUGH_ALLOW_EOL_PLATFORM; that variable is a
            # registered trust bypass now (a security review was right
            # that an end-of-life capture and encode stack cannot be
            # merely recorded), and this script needs no waiver: it
            # publishes artifacts that already exist and calls neither
            # playthrough_check_platform nor playthrough_assert_trusted.
            # Committing is deliberately not gated on the platform --
            # gating it would leave an out-of-support host unable to
            # commit the very disclosure that records the residual.
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
    """One pathspec, and a commit publishes the whole index."""

    def test_staged_work_outside_the_feature_is_refused(self):
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        self.write(os.path.join(self.checkout, "src", "other.cpp"),
                   "// somebody else's change\n")
        self.git("add", "--", "src/other.cpp")
        message = self.refuse(EX_SCOPE, ("creation",))
        self.assertIn("outside playthrough", message)
        self.assertIn("src/other.cpp", message)
        self.assertIn("publishes the whole index", message)

    def test_staged_version_control_configuration_is_refused(self):
        """The two root files are out of scope, staged or not.

        The terminal negation and the binary attributes are
        repository-wide configuration this tree depends on.  This script
        CHECKS them and never commits them, so finding one in the index
        is a refusal that says where it belongs instead of quietly
        publishing it inside a checkpoint about a survivor's save.
        """
        self.write(self.gitignore, SANDBOX_GITIGNORE + "# an edit\n")
        self.git("add", "--", ".gitignore")
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        message = self.refuse(EX_SCOPE, ("creation",))
        self.assertIn(".gitignore", message)
        self.assertIn("commit them separately", message)

    def test_edited_version_control_configuration_is_only_reported(self):
        """Unstaged, it cannot ride along -- so it is named, not fatal.

        Silence would be the problem: a reader expects a step called
        "commit the artifacts" to have taken these two, so the checkpoint
        says out loud that it did not and why.
        """
        self.write(self.gitignore, SANDBOX_GITIGNORE + "# an edit\n")
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        fields, err = self.checkpoint("creation")
        self.assertEqual(fields["COMMITTED"], "yes")
        self.assertIn(".gitignore", err)
        self.assertIn("its own commit", err)
        changed = self.git("show", "--name-only", "--format=", "HEAD",
                           identity=False)
        self.assertNotIn(".gitignore", changed)
        self.assertNotEqual(
            "",
            self.git("status", "--porcelain", "--", ".gitignore",
                     identity=False).strip(),
            msg="the edit should still be waiting for its own commit")

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

    def test_the_commit_holds_only_the_artifact_tree(self):
        self.write(os.path.join(self.checkout, "src", "other.cpp"),
                   "// somebody else's change\n")
        self.take_creation()
        changed = self.git("show", "--name-only", "--format=", "HEAD",
                           identity=False).split("\n")
        for path in [line for line in changed if line]:
            with self.subTest(path=path):
                self.assertTrue(
                    path.startswith("playthrough/"),
                    msg="%r is outside the artifact tree" % path)


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


class TestStagingIsExplicitBatchedAndComplete(CheckpointFixture):
    """How the index is built, which is this script's other constraint.

    Explicit, by artifact class, in bounded batches -- and then held to
    being COMPLETE, because an enumeration that quietly omitted a class
    would leave evidence uncommitted while every other check passed.
    """

    #: The forms of `git add` that must not appear in the source at all.
    BLANKET = re.compile(r"add\s+(?:-A\b|-f\b|--force\b|\.(?:\s|$))")

    def source_lines(self):
        """Every non-comment line of the subject, numbered."""
        with open(os.path.join(TOOLING, SCRIPT_NAME),
                  encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                if line.lstrip().startswith("#"):
                    continue
                yield (number, line)

    def test_the_source_has_no_blanket_or_forced_add(self):
        """-A, a bare '.', and -f are all absent.

        A blanket add would sweep whatever happened to be in the tree
        into a checkpoint, and -f would paper over a broken .gitignore
        negation instead of reporting it.  Asserted against the source,
        because their absence is the property -- a run cannot demonstrate
        that a command was never available to it.
        """
        for number, line in self.source_lines():
            with self.subTest(line=number):
                self.assertIsNone(
                    self.BLANKET.search(line),
                    msg=("line %d stages with a blanket or forced add: "
                         "%r" % (number, line.rstrip())))

    def test_each_artifact_class_is_staged_as_its_own_batch(self):
        self.write(os.path.join(self.dir, "cata-play.mp4"),
                   "not a real film, but a real file\n")
        self.write(os.path.join(self.dir, "timeline.json"), "[]\n")
        _, err = self.take_creation()
        for label in ("pipeline tooling", "narrative and documentation",
                      "engine save and configuration", "captured frames",
                      "record and timeline", "build intermediates",
                      "assembled film"):
            with self.subTest(label=label):
                self.assertIn("staged the %s:" % label, err)

    def test_the_captures_are_staged_in_bounded_batches(self):
        """More captures than one batch holds, staged without a limit.

        A session of any length must not approach the argument-list
        limit, so the frames are chunked.  This writes more than one
        chunk's worth and proves every one of them is tracked.
        """
        with open(os.path.join(TOOLING, SCRIPT_NAME),
                  encoding="utf-8") as handle:
            source = handle.read()
        match = re.search(r"STAGE_BATCH_SIZE=(\d+)", source)
        self.assertIsNotNone(match, msg="the batch bound is declared")
        bound = int(match.group(1))
        self.assertGreater(bound, 0)
        count = bound + 3
        self.write_save()
        self.write_evidence(count)
        fields, err = self.checkpoint("creation")
        self.assertEqual(fields["FRAMES"], str(count))
        self.assertIn("staged the captured frames: %d path(s)" % count,
                      err)
        self.assertEqual(len(self.tracked("playthrough/frames")), count)
        self.assertIn("%d tracked by git, %d on disk" % (count, count),
                      err)

    def test_a_class_nobody_enumerated_is_refused_not_skipped(self):
        """Explicit staging's own failure mode, closed.

        A file directly under playthrough/ that no batch names would
        otherwise be left behind in silence.  The refusal names it and
        says which list to add it to.
        """
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        self.write(os.path.join(self.dir, "stray_artifact.txt"),
                   "nobody enumerated me\n")
        message = self.refuse(EX_COMMIT, ("creation",))
        self.assertIn("stray_artifact.txt", message)
        self.assertIn("stage_artifacts", message)

    def test_bytecode_left_in_the_index_is_refused(self):
        """The index, not just the filesystem, is checked.

        The filesystem sweep cannot see a *.pyc that has already been
        staged and then deleted -- an interrupted earlier run leaves
        exactly that -- so whatever is about to be published is examined
        as well.
        """
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        relative = "playthrough/stray/manifest.cpython-312.pyc"
        path = self.write(os.path.join(self.checkout, relative),
                          "bytecode\n")
        self.git("add", "--", relative)
        os.unlink(path)
        message = self.refuse(EX_SCOPE, ("creation",))
        self.assertIn("interpreter bytecode", message)
        self.assertIn(relative, message)
        self.assertIn("PYTHONDONTWRITEBYTECODE", message)

    def test_an_ignored_path_inside_the_tree_is_refused(self):
        """A directory add skips an ignored file without complaining.

        So the sweep asks for the ignored entries too: a rule placed
        after the terminal negation that re-excludes one path inside this
        tree would otherwise be committed around in perfect silence.
        """
        hidden = "playthrough/userdir/config/lastworld.json"
        self.write(self.gitignore, SANDBOX_GITIGNORE + hidden + "\n")
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        message = self.refuse(EX_SCOPE, ("creation",))
        self.assertIn(hidden, message)
        self.assertIn("IGNORED by git", message)
        self.assertIn(NEGATION_LINE, message)


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

    def test_the_compressed_save_form_is_accepted(self):
        """`#<b64>.sav.zzip` is a real save, not a stray file.

        game::save_player_data writes `playerfile + SAVE_EXTENSION +
        zzip_suffix` when the world has compression enabled
        (src/game_io.cpp:601-641, src/worldfactory.h:25) and
        WORLD_COMPRESSION2 defaults to true, so a gate that insisted on
        the plain spelling would refuse a perfectly ordinary session.
        """
        self.write_save()
        compressed = self.save_file + ".zzip"
        os.rename(self.save_file, compressed)
        self.write_evidence(self.CREATION_ROWS)
        fields, err = self.checkpoint("creation")
        self.assertEqual(fields["CHARACTER"], CHARACTER)
        self.assertIn("%s.zzip" % SAVE_BASENAME, err)
        self.assertTrue(self.is_tracked(
            os.path.relpath(compressed, self.checkout)))

    def test_final_accepts_a_compressed_graveyard_save(self):
        """The same tolerance after a death.

        The archive's inner JSON cannot be read by the gate, so the two
        checks that need it are SKIPPED and said out loud rather than
        reported as passes; the memorial pair and the captured death
        sequence still decide.
        """
        self.take_creation()
        self.play_session()
        persistence = self.write_death_persistence()
        compressed = persistence[0] + ".zzip"
        os.rename(persistence[0], compressed)

        fields, err = self.checkpoint("final")

        self.assertEqual(fields["CHARACTER"], CHARACTER)
        self.assertIn("NOT inspected", err)
        self.assertTrue(self.is_tracked(
            os.path.relpath(compressed, self.checkout)))

    def test_final_accepts_the_engine_death_generation(self):
        """Death moves the survivor; it does not erase persistence."""
        self.take_creation()
        self.play_session()
        persistence = self.write_death_persistence()

        fields, err = self.checkpoint("final")

        self.assertEqual(fields["WORLD"], WORLD)
        self.assertEqual(fields["CHARACTER"], CHARACTER)
        self.assertIn("death persistence", err)
        self.assertIn("- save data", self.message())
        for path in persistence:
            relative = os.path.relpath(path, self.checkout)
            with self.subTest(path=relative):
                self.assertTrue(self.is_tracked(relative))
        self.assertFalse(self.is_tracked(
            "playthrough/userdir/save/%s/%s"
            % (WORLD, SAVE_BASENAME)))

    def test_final_refuses_death_files_without_a_memorial_pair(self):
        self.take_creation()
        self.play_session()
        _, _, memorial_json, _ = self.write_death_persistence()
        os.unlink(memorial_json)

        message = self.refuse(EX_EVIDENCE, ("final",))

        self.assertIn("memorial", message)
        self.assertIn("one matching pair", message)

    def test_final_refuses_death_files_without_observed_death(self):
        self.take_creation()
        self.play_session()
        self.write_death_persistence(mark_record=False)

        message = self.refuse(EX_EVIDENCE, ("final",))

        self.assertIn("captured last-words", message)
        self.assertIn("post-death", message)

    def test_final_refuses_no_live_or_graveyard_survivor(self):
        self.take_creation()
        self.play_session()
        os.unlink(self.save_file)
        os.unlink(self.master)

        message = self.refuse(EX_EVIDENCE, ("final",))

        self.assertIn("no live survivor", message)
        self.assertIn("manual deletion is not a death ending", message)


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


class TestTheLedgerGate(CheckpointFixture):
    """The two out-of-band ledgers, held before anything is staged.

    Every other evidence check in this script is STRUCTURAL -- the counts
    agree, the file exists, the sequence is unbroken -- and a same-sized
    replacement image passes all of them.  These two are the checks that
    read the bytes and the digests, so they are the ones a substitution
    has to get past.
    """

    def test_an_absent_attestation_ledger_is_refused(self):
        """A frame with no attestation is a frame nobody sealed."""
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        os.unlink(self.digests)
        message = self.refuse(EX_EVIDENCE, ("creation",))
        self.assertIn("no capture attestation ledger", message)
        self.assertIn("same-sized image", message)

    def test_an_empty_attestation_ledger_is_refused(self):
        """Present but empty is the same claim as absent."""
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        self.write(self.digests, "")
        message = self.refuse(EX_EVIDENCE, ("creation",))
        self.assertIn("no capture attestation ledger", message)

    def test_a_replaced_frame_is_refused(self):
        """THE SUBSTITUTION EVERY OTHER GATE PASSES.

        The replacement is a real file at the right name, so the count
        identity holds, the sequence is unbroken and every row still
        names a capture that exists.  Only the digest disagrees.
        """
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        self.write(os.path.join(self.frames_dir, "frame_00002.png"),
                   "a different file at the same name\n")
        message = self.refuse(EX_EVIDENCE, ("creation",))
        self.assertIn("manifest.py refused the captures", message)
        self.assertIn("frame 2 is attested as sha256", message)

    def test_an_unattested_frame_is_refused(self):
        """A row whose bytes nothing sealed."""
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        self.write_digests(self.CREATION_ROWS - 1)
        message = self.refuse(EX_EVIDENCE, ("creation",))
        self.assertIn("bytes are not attested", message)

    def test_the_refusal_says_restore_rather_than_re_attest(self):
        """The remedy may not be "seal whatever is there now".

        Re-attesting the file on disk would make every future run pass
        while publishing bytes nobody captured -- the exact move the
        ledger exists to prevent.
        """
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        self.write(os.path.join(self.frames_dir, "frame_00001.png"),
                   "substituted after the fact\n")
        message = self.refuse(EX_EVIDENCE, ("creation",))
        self.assertIn("restoring the captured bytes", message)
        self.assertIn("never by re-attesting", message)

    def test_an_amendment_bound_to_its_line_passes(self):
        """A well-formed correction does not obstruct a checkpoint."""
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        row = self.row(2)
        line = json.dumps(row) + "\n"
        self.write(self.amendments, json.dumps({
            "amendment": 1,
            "amended_ts": "2026-08-05T09:14:02.000Z",
            "frame": 2,
            "field": "commentary",
            "source_sha256": hashlib.sha256(
                line.encode("utf-8")).hexdigest(),
            "recorded": row["commentary"],
            "amended": ("The door at the end is shut and I would "
                        "rather know what is behind it than stand out "
                        "here guessing at it."),
            "basis": ("the capture shows the door still shut, so "
                      "'wondering' overstated what I could see"),
            "reason": "commentary overstated the capture",
        }) + "\n")
        fields, _ = self.checkpoint("creation")
        self.assertEqual(fields["COMMITTED"], "yes")

    def test_an_amendment_whose_digest_no_longer_matches_is_refused(self):
        """The binding is the whole mechanism.

        An amendment names the sha256 of the exact line it corrects.  If
        that digest does not match, the correction describes a line that
        is not there, and applying it to whatever now occupies the row
        would be guessing.
        """
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        self.write(self.amendments, json.dumps({
            "amendment": 1,
            "amended_ts": "2026-08-05T09:14:02.000Z",
            "frame": 2,
            "field": "commentary",
            "source_sha256": "0" * 64,
            "recorded": self.row(2)["commentary"],
            "amended": ("The door at the end is shut and I would "
                        "rather know what is behind it than stand out "
                        "here guessing at it."),
            "basis": ("the capture shows the door still shut, so "
                      "'wondering' overstated what I could see"),
            "reason": "commentary overstated the capture",
        }) + "\n")
        message = self.refuse(EX_EVIDENCE, ("creation",))
        self.assertIn("refused the amendment ledger", message)
        self.assertIn("NEW amendment", message)

    def test_no_amendment_ledger_is_not_a_problem(self):
        """A session with nothing to correct has nothing to carry."""
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        self.assertFalse(os.path.exists(self.amendments))
        fields, _ = self.checkpoint("creation")
        self.assertEqual(fields["COMMITTED"], "yes")

    def test_the_attestation_ledger_is_committed(self):
        """It is evidence, so it is published with the frames."""
        self.take_creation()
        self.assertTrue(
            self.is_tracked("playthrough/build/frame_digests.jsonl"),
            msg="the attestation ledger must be committed; a digest "
                "nobody can read afterwards attests nothing")


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

    def test_the_negation_failing_is_caught_before_anything_is_staged(
            self):
        """The failure that hides itself, made loud -- and made EARLY.

        Without the terminal `!/playthrough/**`, .gitignore's `\\#*` rule
        matches the engine's own character save, `git add` skips it and
        exits 0 -- so every count still tallies and the checkpoint looks
        successful.  `git check-ignore --no-index` is the only honest
        question, and asking it BEFORE staging means the previous commit
        is still the last word when the answer is bad.

        The by-name `git ls-files --error-unmatch` check after the commit
        is kept as the belt-and-braces it always was; it is no longer the
        first line of defence, and its subject matter is proved by
        test_every_artifact_class_is_tracked.
        """
        self.write(self.gitignore,
                   SANDBOX_GITIGNORE.replace(NEGATION_LINE, ""))
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        message = self.refuse(EX_SCOPE, ("creation",))
        self.assertIn("is IGNORED by", message)
        self.assertIn("exit 0", message)
        self.assertIn(NEGATION_LINE, message)
        self.assertFalse(
            self.is_tracked("playthrough/userdir/save/%s/%s"
                            % (WORLD, SAVE_BASENAME)),
            msg="the refusal must leave the save untracked, not commit "
                "a checkpoint without it")

    def test_a_rule_after_the_negation_cannot_hide_one_capture(self):
        """Re-exclusion of a single path, which is the subtler form.

        The captures are staged BY NAME, and `git add` given an explicit
        ignored path fails loudly instead of skipping it -- which is the
        whole reason this script does not hand a directory to one blanket
        add.  Nothing is committed.
        """
        hidden = "playthrough/frames/frame_00003.png"
        self.write(self.gitignore, SANDBOX_GITIGNORE + hidden + "\n")
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        message = self.refuse(EX_COMMIT, ("creation",))
        self.assertIn(hidden, message)
        self.assertIn("captured frames", message)
        self.assertFalse(self.is_tracked(hidden))

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
            self.git("status", "--porcelain", "--untracked-files=all",
                     "--ignored=matching", "--", "playthrough",
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


class TestTheDossierGate(CheckpointFixture):
    """Written before play, and in the history before the first frame.

    The acceptance gate reads that ordering out of `git log`, so the
    checkpoint that commits the creation is what establishes it and a
    dossier that is not there when it runs cannot be put back into the
    right place afterwards.
    """

    def dossier(self):
        return os.path.join(self.dir, "dossier.md")

    def test_creation_without_a_dossier_is_refused(self):
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        os.unlink(self.dossier())
        message = self.refuse(EX_EVIDENCE, ("creation",))
        self.assertIn("playthrough/dossier.md", message)
        self.assertIn("BEFORE the first keystroke", message)

    def test_an_empty_dossier_is_refused(self):
        """A placeholder is the same absence with a file in the way."""
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        self.write(self.dossier(), "")
        message = self.refuse(EX_EVIDENCE, ("creation",))
        self.assertIn("is empty", message)

    def test_final_refuses_a_dossier_that_was_never_committed(self):
        """Untracked, the ordering is unprovable whatever it says."""
        self.take_creation()
        self.play_session()
        self.git("rm", "--cached", "--quiet", "--",
                 "playthrough/dossier.md")
        message = self.refuse(EX_LIFECYCLE, ("final",))
        self.assertIn("git does not track it", message)

    def test_final_refuses_a_dossier_deleted_between_checkpoints(self):
        self.take_creation()
        self.play_session()
        os.unlink(self.dossier())
        message = self.refuse(EX_EVIDENCE, ("final",))
        self.assertIn("playthrough/dossier.md", message)

    def test_the_dossier_is_committed_by_the_creation_checkpoint(self):
        """And its commit is an ancestor of the first capture's.

        `git merge-base --is-ancestor` holds for a commit and itself, so
        the two landing together is the earliest the ordering allows --
        which is exactly what the creation checkpoint is for.
        """
        self.take_creation()
        self.assertTrue(self.is_tracked("playthrough/dossier.md"))
        dossier_commit = self.first_commit_touching(
            "playthrough/dossier.md")
        frame_commit = self.first_commit_touching(
            "playthrough/frames/frame_00001.png")
        self.assertNotEqual("", dossier_commit)
        self.assertNotEqual("", frame_commit)
        self.assertEqual(0, self.git_status_of(
            ("merge-base", "--is-ancestor", dossier_commit,
             frame_commit)))

    def first_commit_touching(self, path):
        """The OLDEST commit that touched one path."""
        history = [line for line in self.git(
            "log", "--format=%H", "--", path,
            identity=False).split("\n") if line]
        return history[-1] if history else ""

    def git_status_of(self, args):
        """git's exit status, for a question with a boolean answer."""
        result = subprocess.run(
            [os.path.join(self.bin, "git")] + list(args),
            cwd=self.checkout, capture_output=True,
            env={"PATH": self.bin, "GIT_CONFIG_GLOBAL": "/dev/null",
                 "GIT_CONFIG_NOSYSTEM": "1"},
            timeout=60)
        return result.returncode


class TestTheScriptItself(unittest.TestCase):
    """Properties of the file, not of a run.

    The same three the sibling scripts' suites assert, because a script
    that no longer parses, no longer passes shellcheck or is no longer
    executable is broken before any behaviour of it can be tested.
    """

    def test_it_parses(self):
        result = subprocess.run(
            ["/bin/bash", "-n", os.path.join(TOOLING, SCRIPT_NAME)],
            capture_output=True, timeout=120)
        self.assertEqual(result.returncode, 0,
                         msg=result.stderr.decode("utf-8", "replace"))

    def test_it_is_shellcheck_clean(self):
        if shutil.which("shellcheck") is None:
            self.skipTest("shellcheck is not installed")
        result = subprocess.run(
            ["shellcheck", "-x", SCRIPT_NAME],
            cwd=TOOLING, capture_output=True, timeout=300)
        self.assertEqual(
            result.returncode, 0,
            msg="this script is shellcheck-clean, including the -x pass "
                "that follows env.sh:\n%s"
                % result.stdout.decode("utf-8", "replace"))

    def test_it_is_executable(self):
        path = os.path.join(TOOLING, SCRIPT_NAME)
        self.assertTrue(os.stat(path).st_mode & stat.S_IXUSR)

    def test_it_is_strict(self):
        """`set -euo pipefail`, and errtrace on top of it.

        Every other executable in this folder sets those options itself,
        because env.sh deliberately does not: shell options set at the
        top level of a SOURCED file are imposed on the calling shell.
        """
        with open(os.path.join(TOOLING, SCRIPT_NAME),
                  encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("set -euo pipefail", source)
        self.assertIn("set -o errtrace", source)


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
