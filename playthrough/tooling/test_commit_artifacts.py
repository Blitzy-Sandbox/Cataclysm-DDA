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
GIT_CONFIG_NOSYSTEM=1 and GIT_CONFIG_GLOBAL pointed at an EMPTY FILE
INSIDE THE SANDBOX so the host's own configuration cannot make a test
pass.  That is also how the missing identity case is produced: drop those
four variables and git has nothing to resolve.

GIT_CONFIG_GLOBAL is a sandbox file rather than /dev/null, and the reason
is a hazard that was measured rather than imagined.  The subject writes
`git config --local`; a regression that widened that to `--global` was
introduced deliberately to check these tests would catch it, and git
performed the write the way it performs every configuration write --
create a lock file beside the target, then rename it over the target.
With the target set to /dev/null that rename REPLACED THE HOST'S NULL
DEVICE with a regular file containing git's error message, and every
later `> /dev/null` on the host appended to it.  A suite whose failure
mode is damaging the machine it runs on is not a safe suite, so the
global scope is aimed inside the temporary directory, where a stray
write lands harmlessly and is thrown away with the rest of the sandbox --
and where it can be read back byte for byte as evidence that no such
write happened.

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
import time
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

# The attribute rows the feature depends on, every one of them.  A
# checkpoint reads HEAD's OWN .gitattributes and refuses when they are
# missing, because `* text=auto` alone leaves the film, the save and the
# compressed map archives to content detection rather than to a
# declaration -- so a sandbox without them is a sandbox in which no
# checkpoint can be taken, which is the behaviour under test rather than
# an obstacle to it.  The last row is the whitespace waiver over the
# engine's own tree, and its position matters: git applies the last
# matching pattern, so it is written after the suffix rows and asserted
# not to have disturbed them.
SANDBOX_GITATTRIBUTES = (
    "* text=auto\n"
    "*.mp4 binary\n"
    "*.zzip binary\n"
    "*.sav binary\n"
    "*.gsav binary\n"
    "*.srt text\n"
    "*.jsonl text\n"
    "playthrough/userdir/** -whitespace\n"
)

# The rows a checkpoint requires HEAD to carry, in the spelling it
# compares against, so a test can remove exactly one of them.
REQUIRED_ATTRIBUTE_ROWS = (
    "*.mp4 binary",
    "*.zzip binary",
    "*.sav binary",
    "*.gsav binary",
    "*.srt text",
    "*.jsonl text",
    # The whitespace waiver over the engine's own tree.  Two files the
    # game writes end with a blank line, so `git diff --check` reports
    # them; the bytes are evidence and are not edited to please a linter.
    "playthrough/userdir/** -whitespace",
)

# What git must APPLY, per representative artifact, which is a different
# question from which rows are written down: `binary` is a macro for
# `-text -diff -merge`, so a binary artifact is one whose `text`
# attribute is unset and a text artifact is one whose `text` is set.  The
# paths are the real spellings this feature commits.
ATTRIBUTE_WITNESSES = (
    ("playthrough/cata-play.mp4", "text", "unset"),
    ("playthrough/userdir/save/World/maps.zzip", "text", "unset"),
    ("playthrough/userdir/save/World/#character.sav", "text", "unset"),
    ("playthrough/userdir/save/World/master.gsav", "text", "unset"),
    ("playthrough/transcript.srt", "text", "set"),
    ("playthrough/manifest.jsonl", "text", "set"),
    # The waiver, measured on BOTH sides of its boundary: it has to reach
    # the engine's tree and it must not reach anything authored here.
    ("playthrough/userdir/config/debug.log", "whitespace", "unset"),
    ("playthrough/transcript.md", "whitespace", "unspecified"),
)

# The final report's three sections, in the order the requirement fixes
# them.  Spelled out here rather than imported from the subject, so a
# test that passed would not be passing against a rewritten contract.
REPORT_SECTIONS = (
    "## A) Screen Recording and Animation",
    "## B) Character Creation",
    "## C) Playing the Game",
)


def report_text(sections=REPORT_SECTIONS):
    """A final report carrying `sections`, with prose under each.

    Level-three subsections are included on purpose: the real report has
    many, and a gate that counted those would refuse it.
    """
    body = ["# %s: the recording, the survivor, the session" % CHARACTER,
            "",
            "What follows is what was recorded and what it shows.",
            ""]
    for section in sections:
        body.extend([
            section,
            "",
            "### What this section covers",
            "",
            "One paragraph, so the section is not merely a heading.",
            "",
        ])
    return "\n".join(body)


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


def runtime_root():
    """The verified runtime root a nominated one has to live beneath.

    env.sh proves ONE ancestor is a real, owner-only 0700 directory owned
    by this user and refuses any nominated root outside it, so a sandbox
    cannot simply use its own temporary base.  The variable is read first
    so a host that sets it is honoured, with env.sh's own default as the
    fallback.
    """
    root = os.environ.get("XDG_RUNTIME_DIR") or "/tmp/xdg"
    try:
        os.makedirs(root, mode=0o700, exist_ok=True)
    except OSError:
        pass
    return root


def _unlink_if_present(path):
    """Remove `path` if it is still there; used for a planted fifo.

    shutil.rmtree removes a fifo perfectly well -- this exists so the
    special file is gone even if the tree removal is what fails.
    """
    try:
        os.unlink(path)
    except OSError:
        pass


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
        # The global scope, aimed inside the sandbox.  Empty, so it
        # supplies no identity; a real file, so a write that reached it
        # would be visible here instead of landing on the host.  See the
        # module docstring for the incident that made this necessary.
        self.global_config = os.path.join(self.root, "global.gitconfig")
        self.write(self.global_config, "")
        # THE RUNTIME ROOT.  Two constraints meet here and only one
        # directory satisfies both: commit_artifacts.sh refuses a
        # nominated root INSIDE the checkout, because .gitignore's
        # terminal negation re-includes everything under playthrough/ and
        # the root holds the X authority cookie -- and env.sh refuses one
        # that is not BENEATH the verified XDG runtime root, because only
        # that ancestor has been proved to be an owner-only 0700
        # directory.  Measured: a root in the sandbox base was refused
        # with exit 8 before a single gate ran.  So it goes under
        # /tmp/xdg, per test, and is removed with the test.
        #
        # It matters to these tests because it is where the acceptance
        # report the `attest` checkpoint publishes is measured TO.
        self.runtime = tempfile.mkdtemp(prefix="blitzy_checkpoint_rt_",
                                        dir=runtime_root())
        self.addCleanup(shutil.rmtree, self.runtime, True)
        self.acceptance_scratch = os.path.join(
            self.runtime, "acceptance-report.txt")
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
        # The final report, written the way a finished recording is
        # delivered.  Seeded in the fixture for the same reason the
        # dossier is: `final` REQUIRES it, so a test about the lifecycle
        # would otherwise be a test about its absence.
        self.report = os.path.join(self.dir, "REPORT.md")
        self.write(self.report, report_text())
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

    def write_save(self, revision=""):
        """The engine-managed state a checkpoint records.

        `revision` exists so the save can be REWRITTEN with different
        bytes, which is what the engine does on Save and Quit.  The
        `final` checkpoint asserts that it recorded at least one path
        under the userdir, so a fixture whose save never changes after
        creation would model a session that never closed.
        """
        suffix = (" (%s)" % revision) if revision else ""
        self.write(self.master, "master state%s\n" % suffix)
        self.write(self.save_file, "character state%s\n" % suffix)
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
            "GIT_CONFIG_GLOBAL": self.global_config,
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

        NOT `git config`, and the distinction is what makes the identity
        tests mean anything: the script's job is to take an identity that
        already resolves and RECORD it in this repository, so a fixture
        that had already written it locally would be handing over the
        answer.  These four are the mechanism git itself documents for
        supplying an identity without configuring a repository, which is
        also the arrangement inside the container -- an identity in the
        environment, nothing in the tree -- that the local write exists
        to survive.
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
            "PLAYTHROUGH_RUNTIME_DIR": self.runtime,
            "GIT_CONFIG_GLOBAL": self.global_config,
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
            env={"PATH": self.bin, "GIT_CONFIG_GLOBAL": self.global_config,
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
            env={"PATH": self.bin, "GIT_CONFIG_GLOBAL": self.global_config,
                 "GIT_CONFIG_NOSYSTEM": "1"},
            timeout=60)
        return result.returncode == 0

    def git_config_text(self):
        """The sandbox's own configuration file, read as a file.

        Deliberately NOT `git config --get user.name`, which would
        resolve across every scope and answer a different question.  What
        several tests need to know is what THIS REPOSITORY records, and
        reading the one file the local scope lives in is the form of that
        question with no other scope in it.
        """
        path = os.path.join(self.checkout, ".git", "config")
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()

    def local_identity(self):
        """The (name, address) pair this repository records, or blanks."""
        return tuple(
            self.git("config", "--local", "--get", key, identity=False,
                     check=False).strip()
            for key in ("user.name", "user.email"))

    def script_source(self):
        """The real commit_artifacts.sh text, for contract assertions.

        Used where a control's ORDER or SHAPE is the thing under test and
        a behavioural test could not reach it -- see
        test_an_in_repository_runtime_root_is_refused, whose control sits
        behind env.sh's own earlier refusal.
        """
        with open(os.path.join(TOOLING, SCRIPT_NAME),
                  encoding="utf-8") as handle:
            return handle.read()

    def hygiene_names(self):
        """The HYGIENE_NAMES array, parsed out of the script."""
        source = self.script_source()
        start = source.index("readonly -a HYGIENE_NAMES=(")
        body = source[start:source.index(")", start)]
        return [
            line.strip().strip('"')
            for line in body.splitlines()[1:]
            if line.strip() and not line.strip().startswith("#")
        ]

    # -- the whole lifecycle, for tests that need it in place --------

    def take_dossier(self, **environment):
        """Commit the dossier alone, which is where a lifecycle starts.

        The dossier is already tracked from the fixture's first commit,
        so this is the ordering step rather than the introducing one --
        which is the same thing a re-run does in a real checkout.
        """
        return self.checkpoint("dossier", **environment)

    def forget_dossier(self):
        """Take the dossier back out of the history, leaving it on disk.

        The fixture's first commit tracks it, because that is the real
        order of events.  Some tests need the moment BEFORE that -- the
        dossier written but not yet published -- which is where the
        `dossier` checkpoint has something to introduce and where
        `creation` must refuse.
        """
        self.git("rm", "--quiet", "--cached", "--",
                 "playthrough/dossier.md")
        self.git("commit", "--quiet", "-m",
                 "Take the dossier back out of the history")
        self.assertFalse(self.is_tracked("playthrough/dossier.md"))

    def commit_worktree_file(self, relative, text):
        """Change one tracked file and commit it outside the lifecycle.

        Used to put a repository into a state a checkpoint must refuse --
        a committed .gitignore without the negation, say -- without going
        anywhere near the subject.
        """
        self.write(os.path.join(self.checkout, relative), text)
        self.git("add", "--", relative)
        self.git("commit", "--quiet", "-m", "Change %s" % relative)

    def touched_by(self, revision="HEAD"):
        """The paths one commit recorded, as a sorted list."""
        listing = self.git("diff-tree", "--no-commit-id", "--name-only",
                           "-r", revision, identity=False)
        return sorted(line for line in listing.split("\n") if line)

    def introduced(self, path):
        """The oldest commit that touched `path`.

        The same reading the subject and the acceptance gate both make,
        so an ordering assertion here is the ordering they assert.
        """
        log = self.git("log", "--format=%H", "--", path, identity=False)
        commits = [line for line in log.split("\n") if line]
        self.assertTrue(commits,
                        msg="no commit ever touched %s" % path)
        return commits[-1]

    def take_creation(self, **environment):
        """Write the creation evidence and take the first checkpoint."""
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        return self.checkpoint("creation", **environment)

    def play_session(self):
        """Grow the record the way gameplay grows it.

        AND REWRITE THE SAVE, because that is what happens: the survivor
        plays, then saves and quits, and the engine writes the save out
        again.  The `final` checkpoint asserts that it recorded a change
        under the userdir -- a final commit carrying no save is the
        second of the two mandated commits in name only -- so a fixture
        that grew only the record would model a session nobody closed.
        """
        self.write_save(revision="after the session")
        return self.write_evidence(
            self.CREATION_ROWS + self.SESSION_ROWS)

    def short_head(self):
        """HEAD as the ten characters the gate's report names it by.

        A sibling of head() rather than a replacement: that one answers
        "is there a commit at all" and returns empty before the first,
        which is a different question from "which commit, abbreviated
        the way the report abbreviates it".
        """
        return self.git("rev-parse", "--short=10", "HEAD",
                        identity=False).strip()

    def write_acceptance_report(self, verdict="pass",
                                phase="post-commit", measured=None,
                                body="PASS  everything the gate asks\n"):
        """A measurement for `attest` to publish, at the scratch path.

        Shaped like verify_artifacts.sh's own output: prose, then the
        closing KEY=value machine block a caller can act on.  `measured`
        defaults to the CURRENT HEAD, which is what makes the report
        about the tree it is being committed onto -- the three overrides
        exist so each refusal can be reached on its own.
        """
        if measured is None:
            measured = "HEAD %s" % self.short_head()
        return self.write(self.acceptance_scratch, (
            "verify_artifacts.sh -- the acceptance gate\n"
            "measuring the tree at %s\n"
            "%s"
            "VERIFY_PHASE=%s\n"
            "VERIFY_MEASURED_COMMIT=%s\n"
            "VERIFY_CHECKS=122\n"
            "VERIFY_FAILURES=0\n"
            "VERIFY=%s\n") % (measured, body, phase, measured,
                              verdict))

    def write_media(self, revision=""):
        """The derived artifacts `media` exists to commit.

        Written AFTER `final` on purpose.  `final` stages the whole tree
        exhaustively, so a fixture that produced the film beforehand would
        leave `media` with nothing to commit -- and a checkpoint that
        commits nothing records no trailer, which makes an ordering test
        pass or fail on the fixture rather than on the lifecycle.
        """
        self.write(os.path.join(self.dir, "cata-play.mp4"),
                   "a film%s\n" % revision)
        self.write(os.path.join(self.dir, "cata-play-cc.mp4"),
                   "a captioned film%s\n" % revision)

    def reach_media(self):
        """A history with a published `final` in it."""
        self.take_creation()
        self.play_session()
        self.checkpoint("final")
        self.write_media()

    def reach_attest(self, **report):
        """Everything `attest` needs except the two documents.

        The report is written AFTER the media checkpoint on purpose: it
        names the commit it measured, and the commit it has to name is
        the one `attest` will be taken on top of.
        """
        self.reach_media()
        self.checkpoint("media")
        self.write_acceptance_report(**report)


class TestItNeverWritesTheIdentityAnywhere(CheckpointFixture):
    """Where the committer identity may be written: nowhere.

    THIS CLASS USED TO ASSERT THE OPPOSITE, and the reversal is the
    finding.  The script wrote the resolved pair into the checkout's own
    configuration with `git config --local user.name` / `user.email`, and
    the justification was concrete: the render and capture stages run
    inside the declared container, which mounts the checkout, sets its own
    HOME and forwards no GIT_*, so an identity living only in the invoking
    user's ~/.gitconfig does not exist in there and a checkpoint taken
    inside the image exited 3.

    Three things were wrong with it.  It contradicted the script's own
    opening contract, which states in as many words that it never writes
    git configuration in any scope -- a file that says "never" at the top
    and does it in the middle has one of the two wrong.  The execution
    environment this evidence is produced in FORBIDS running those
    commands at any scope and fixes the committer identity itself, so the
    write was not a service but a prohibited act that happened to be
    load-bearing.  And it bought no invariance: the value written was
    whatever the HOST resolved, so what landed in .git/config still
    depended on who ran it first -- persistence, not stability -- and the
    acceptance gate then read it back and reported it as a property of the
    repository.  A companion finding caught that from the other end: the
    delivered acceptance report CLAIMED a repository-local identity that
    was never there.

    So the contract is now what the header always said: ASSERT that an
    identity resolves, REPORT which scope answered, write nothing.  The
    container gets the pair forwarded as GIT_AUTHOR_* / GIT_COMMITTER_* by
    supported_env.sh, which is git's own mechanism for it and leaves
    nothing behind in the tree.
    """

    # The script's one calling convention for git, with the first flag
    # captured.  Deliberately anchored on the "${GIT}" expansion rather
    # than on the words "git config": several comments and log messages
    # QUOTE the retired command in prose, deliberately, so a reader learns
    # what is no longer done -- and a looser pattern reads those as
    # invocations and reports the defect as present.
    INVOCATION = re.compile(r'"\$\{GIT\}"\s+config\s+(\S+)')

    def config_invocations(self):
        """Every `git config` the source actually runs, with its flag."""
        found = []
        with open(os.path.join(TOOLING, SCRIPT_NAME),
                  encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                if line.lstrip().startswith("#"):
                    continue
                match = self.INVOCATION.search(line)
                if match:
                    found.append((number, match.group(1), line.strip()))
        return found

    def test_no_git_config_call_can_write(self):
        """Every surviving invocation is a READ.

        `git config --local --get KEY` answers a question; `git config
        --local KEY VALUE` changes the answer.  The difference is the
        whole contract, so it is read off the source rather than inferred
        from behaviour: a write reintroduced here would be caught even if
        no test happened to exercise the path that reached it.
        """
        for number, flag, line in self.config_invocations():
            self.assertIn(
                "--get", line,
                msg=("line %d runs a git config that is not a read: %r"
                     % (number, line)))
            self.assertEqual(
                flag, "--local",
                msg=("line %d reaches outside this repository: %r"
                     % (number, line)))

    def test_the_global_configuration_is_byte_identical_afterwards(self):
        """The proof that ~/.gitconfig is not touched either.

        The global scope every test already runs with is a REAL, WRITABLE
        file inside the sandbox -- not /dev/null, which cannot hold a
        write and so could never show one -- and it is compared byte for
        byte across a whole lifecycle.  The system scope is unreachable in
        the first place because GIT_CONFIG_NOSYSTEM stays set.
        """
        original = "[core]\n\tpager = cat\n"
        self.write(self.global_config, original)
        self.take_creation()
        self.play_session()
        self.checkpoint("final")
        with open(self.global_config, "r", encoding="utf-8") as handle:
            self.assertEqual(
                handle.read(), original,
                msg="the script wrote into the global configuration")

    def test_a_whole_lifecycle_records_no_local_identity(self):
        """The behaviour the retired write made impossible to have.

        A checkout that carried none before carries none after, so the
        acceptance gate reads the same absence the operator started with
        and no report can claim a repository-local pair that is not there.
        """
        self.assertNotIn("user", self.git_config_text())
        self.take_creation()
        self.play_session()
        self.checkpoint("final")
        self.assertEqual(self.local_identity(), ("", ""))
        self.assertNotIn("user", self.git_config_text())

    def test_the_broader_scope_is_named_when_it_is_the_one_answering(
            self):
        """A reader has to be able to tell the two facts apart.

        "An identity resolves" and "an identity resolves from THIS
        checkout" are different, and the second is the one the plan asked
        for and this environment cannot supply.  Saying which one held is
        how the divergence reaches the report instead of being assumed
        away.
        """
        _, err = self.take_creation()
        self.assertIn("BROADER scope than this checkout", err)
        self.assertIn(AUTHOR_NAME, err)

    def test_a_matching_local_pair_is_reported_and_left_alone(self):
        name, mail = AUTHOR_NAME, AUTHOR_EMAIL
        self.git("config", "--local", "user.name", name)
        self.git("config", "--local", "user.email", mail)
        _, err = self.take_creation()
        self.assertIn("recorded by THIS checkout's own configuration",
                      err)
        self.assertEqual(self.local_identity(), (name, mail))

    def test_a_local_pair_that_disagrees_is_refused_not_rewritten(self):
        """The disagreement is real and the response changed.

        It used to REPLACE both values, on the reasoning that the
        configuration and the history are one fact and the gate reads the
        configuration.  The reasoning was sound and the remedy was not
        this script's to apply: rewriting configuration is exactly what it
        is not allowed to do.  So the disagreement is now a refusal that
        names both pairs and leaves the checkout exactly as found -- the
        operator decides which of the two is wrong.
        """
        self.git("config", "--local", "user.name", "Somebody Else")
        self.git("config", "--local", "user.email", "else@example.org")
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        message = self.refuse(EX_IDENTITY, ("creation",))
        self.assertIn("Somebody Else", message)
        self.assertIn(AUTHOR_NAME, message)
        self.assertIn("does not rewrite git configuration", message)
        # And nothing was changed on the way out.
        self.assertEqual(self.local_identity(),
                         ("Somebody Else", "else@example.org"))

    def test_a_half_written_local_pair_is_a_disagreement_too(self):
        """One value present is still a pair that does not match.

        This is the case a "both present" comparison cannot reach, and
        under the retired code it was the one that produced a MIXED
        identity by completing the missing half.
        """
        self.git("config", "--local", "user.name", "Somebody Else")
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        message = self.refuse(EX_IDENTITY, ("creation",))
        self.assertIn("Somebody Else", message)
        self.assertEqual(self.local_identity(), ("Somebody Else", ""))

    def test_a_missing_identity_is_still_a_refusal(self):
        """It asserts an identity; it does not invent one.

        And the refusal leaves the configuration as empty as it found it,
        so a refused run cannot be the thing that decides who commits
        here.
        """
        text = self.refuse(EX_IDENTITY, ("creation",), identity=False)
        self.assertIn("WILL NOT INVENT AN IDENTITY", text)
        self.assertNotIn("user", self.git_config_text())

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
        self.assertIn("WILL NOT INVENT AN IDENTITY", message)
        self.assertIn("nothing here to persist", message)

    def test_the_refusal_names_the_environment_remedy(self):
        """The remedy is to supply an identity, not to have one chosen.

        This script persists an identity that already resolves; it does
        not decide who commits.  So the message points at the two places
        an identity legitimately comes from -- a configuration of the
        operator's own, or the standard GIT_* environment -- rather than
        at a value it could have made up.
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


class TestTheCredentialGate(CheckpointFixture):
    """A credential in .git/config is not readable by anybody else.

    This checkout is provisioned with a push URL of the shape
    https://x-access-token:<secret>@host/..., which puts a live bearer
    token in a plain file.  Removing it is not available -- with
    credential.helper empty that URL is the repository's only
    authentication -- and rotating it is the platform's act.  What IS in
    this step's power is the file's mode, so a config that carries a
    credential while group or other can read it is a refusal.
    """

    def config_path(self):
        return os.path.join(self.checkout, ".git", "config")

    def embed_credential(self, mode):
        """Give the sandbox a credential-bearing remote at `mode`."""
        path = self.config_path()
        with open(path, "a", encoding="utf-8") as handle:
            handle.write('[remote "origin"]\n\turl = '
                         "https://x-access-token:s3cr3t@example.invalid"
                         "/repo.git\n")
        os.chmod(path, mode)
        return path

    def test_a_world_readable_credential_refuses_the_checkpoint(self):
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        self.embed_credential(0o644)
        message = self.refuse(EX_REPO, ("creation",))
        self.assertIn("carries a credential", message)
        self.assertIn("644", message)
        self.assertIn("chmod 600", message)

    def test_a_group_readable_credential_is_refused_too(self):
        """0640 exposes it to a group, which is still not the owner."""
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        self.embed_credential(0o640)
        message = self.refuse(EX_REPO, ("creation",))
        self.assertIn("carries a credential", message)
        self.assertIn("640", message)

    def test_an_owner_only_credential_commits_and_says_so(self):
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        self.embed_credential(0o600)
        _, err = self.checkpoint("creation")
        self.assertIn("readable only by its owner", err)
        self.assertIn("the platform's to", err)

    def test_a_config_with_no_credential_is_not_held_to_the_mode(self):
        """Nothing secret in it means nothing for the mode to expose."""
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        os.chmod(self.config_path(), 0o644)
        _, err = self.checkpoint("creation")
        self.assertIn("embeds no credential", err)

    def test_the_gate_is_not_a_silent_repair(self):
        """A refusal LEAVES the mode wide.

        Tightening it quietly would erase the only evidence that the
        credential had ever been exposed, and the run that produced the
        artifacts would still have been the exposed one.
        """
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        path = self.embed_credential(0o644)
        self.refuse(EX_REPO, ("creation",))
        self.assertEqual(0o644, os.stat(path).st_mode & 0o777)


class TestMutatingGitRunsNoHook(CheckpointFixture):
    """`git commit` executes hooks; this step does not let it.

    A hook runs with the checkpoint's privileges at the moment the
    credential in .git/config is reachable, so every mutating git call
    is made with core.hooksPath pointed at an empty verified directory.
    """

    def hook(self, name, body):
        """Plant an executable hook in the sandbox repository."""
        hooks = os.path.join(self.checkout, ".git", "hooks")
        os.makedirs(hooks, exist_ok=True)
        path = os.path.join(hooks, name)
        self.write(path, body)
        os.chmod(path, 0o755)
        return path

    def test_a_planted_pre_commit_hook_does_not_run(self):
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        witness = os.path.join(self.root, "hook-ran")
        self.hook("pre-commit",
                  "#!/bin/sh\ntouch %s\nexit 0\n" % witness)
        self.checkpoint("creation")
        self.assertFalse(
            os.path.exists(witness),
            msg="a pre-commit hook ran during a checkpoint commit")

    def test_a_failing_hook_cannot_block_the_checkpoint(self):
        """A hook that exits non-zero would veto the commit.

        Which is the same reach, seen from the other side: whoever can
        plant a file can stop the evidence being published.
        """
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        self.hook("pre-commit", "#!/bin/sh\nexit 1\n")
        self.checkpoint("creation")

    def test_every_post_commit_hook_is_contained_as_well(self):
        """post-commit runs AFTER the commit, so it is not a veto.

        It is contained for the other reason: it is the hook with the
        clearest read on a freshly published tree.
        """
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        witness = os.path.join(self.root, "post-ran")
        self.hook("post-commit",
                  "#!/bin/sh\ntouch %s\nexit 0\n" % witness)
        self.checkpoint("creation")
        self.assertFalse(os.path.exists(witness))

    def test_a_configured_hooks_path_cannot_win_it_back(self):
        """-c on the command line outranks every configuration file."""
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        elsewhere = os.path.join(self.root, "other-hooks")
        os.makedirs(elsewhere)
        witness = os.path.join(self.root, "configured-hook-ran")
        path = os.path.join(elsewhere, "pre-commit")
        self.write(path, "#!/bin/sh\ntouch %s\nexit 0\n" % witness)
        os.chmod(path, 0o755)
        self.git("config", "core.hooksPath", elsewhere, identity=False)
        self.checkpoint("creation")
        self.assertFalse(os.path.exists(witness))

    def test_the_commit_is_made_through_the_wrapper(self):
        """No `"${GIT}" commit` remains -- structurally, not by luck."""
        source = self.script_source()
        self.assertNotIn('"${GIT}" commit', source)
        self.assertEqual(2, source.count("git_mutate commit"))
        self.assertIn("core.hooksPath=$(hooks_void)", source)

    def test_the_hooks_directory_must_be_empty(self):
        """An inherited path with contents is a refusal, not a purge."""
        source = self.script_source()
        self.assertIn("-mindepth 1 -print -quit", source)
        self.assertIn("is not empty", source)


class TestTheCommitPublishesWhatWasValidated(CheckpointFixture):
    """The staged blobs are bound to the tree the commit produced."""

    def test_a_successful_checkpoint_reports_the_binding(self):
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        _, err = self.checkpoint("creation")
        self.assertIn("published exactly the", err)
        self.assertIn("object(s) that were staged", err)

    def test_the_comparison_is_object_names_from_both_sides(self):
        """Index blobs against tree blobs, not file contents.

        Comparing contents would re-read the very bytes whose stability
        is in question; comparing object names asks git what it stored.
        """
        source = self.script_source()
        self.assertIn("ls-files --stage", source)
        self.assertIn("ls-tree -r --full-tree", source)
        self.assertIn("assert_commit_tree_matches_index", source)

    def test_a_mismatch_is_reported_and_never_rewritten(self):
        source = self.script_source()
        self.assertIn("does not publish the objects that were", source)
        self.assertIn("it is not rewritten", source)


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
            env={"PATH": self.bin, "GIT_CONFIG_GLOBAL": self.global_config,
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
        """The two root files are out of scope of a SESSION checkpoint,
        staged or not.

        The terminal negation and the binary attributes are
        repository-wide configuration this tree depends on.  A session
        checkpoint CHECKS them and never commits them -- they have a
        milestone of their own -- so finding one in the index here is a
        refusal that says where it belongs instead of quietly publishing
        it inside a checkpoint about a survivor's save.
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

    def test_a_pathname_that_is_only_a_newline_cannot_escape(self):
        """THE ONE PATHNAME THAT USED TO WALK STRAIGHT THROUGH.

        git speaks NUL for exactly this reason, and the refusal used to
        take that NUL-delimited stream and re-emit it one path per LINE
        before counting it.  A file whose name is a single newline
        character therefore arrived as two empty records, both of which
        the reader skipped as blank -- so the count came out zero, the
        gate said the index was clean, and the commit published a path
        from outside the feature.  A refusal that can be switched off by
        naming a file oddly is not a boundary, so the NUL now runs end to
        end and nothing is skipped.
        """
        hostile = os.path.join(self.checkout, "\n")
        with open(hostile, "w", encoding="utf-8") as handle:
            handle.write("outside the feature entirely\n")
        self.addCleanup(os.unlink, hostile)
        self.git("add", "--", "\n")
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        message = self.refuse(EX_SCOPE, ("creation",))
        self.assertIn("1 change(s) outside playthrough", message)
        self.assertIn("publishes the whole index", message)

    def test_a_hostile_pathname_is_rendered_as_itself(self):
        """Counting it is half the job; naming it is the other half.

        A path printed raw into the message would break the line it was
        on and leave the operator guessing which file to unstage, so each
        one is rendered with bash's own %q quoting.
        """
        directory = os.path.join(self.checkout, "src")
        hostile = os.path.join(directory, "we\nird.cpp")
        with open(hostile, "w", encoding="utf-8") as handle:
            handle.write("// still not ours\n")
        self.addCleanup(os.unlink, hostile)
        self.git("add", "--", "src/we\nird.cpp")
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        message = self.refuse(EX_SCOPE, ("creation",))
        self.assertIn("1 change(s) outside playthrough", message)
        self.assertIn("$'src/we\\nird.cpp'", message)


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

    # -- M-21: runtime and auth state, which is worse than derived ----

    def test_a_planted_x_cookie_is_refused(self):
        """The credential case, and the reason this list grew.

        Everything above is merely not evidence.  An Xauthority cookie is
        a credential: whoever holds it can read the screen being captured
        and inject keystrokes into the session.  A commit cannot be
        un-published, so this one has to be caught before staging.
        """
        message = self.refuse_over("Xauthority")
        self.assertIn("Xauthority", message)

    def test_a_planted_pid_file_is_refused(self):
        message = self.refuse_over(os.path.join("run", "xvfb.pid"))
        self.assertIn("xvfb.pid", message)

    def test_a_planted_ownership_record_is_refused(self):
        message = self.refuse_over("x-ownership99")
        self.assertIn("x-ownership99", message)

    def test_a_planted_stage_error_capture_is_refused(self):
        message = self.refuse_over("capture-stage-1234.err")
        self.assertIn("capture-stage-1234.err", message)

    def test_the_requirements_lock_is_not_mistaken_for_a_runtime_lock(
            self):
        """THE FALSE POSITIVE THAT WOULD HAVE BROKEN EVERY CHECKPOINT.

        `*.lock` is the obvious pattern for the runtime locks and it is
        deliberately absent, because playthrough/tooling/requirements.lock
        is a REQUIRED tracked artifact -- the hash-pinned install contract
        for the six declared libraries.  Adding the pattern would refuse
        every checkpoint the pipeline can take.  Caught by running the
        candidate patterns over the real tree before shipping them; this
        test is what keeps it caught.
        """
        self.assertNotIn("*.lock", self.hygiene_names())
        # And a checkpoint over a tree containing it still succeeds.
        self.write(os.path.join(self.dir, "tooling",
                                "requirements.lock"),
                   "moviepy==2.2.1\n")
        self.take_creation()

    def test_the_engine_character_log_is_not_mistaken_for_a_log(self):
        """`*.log` is absent for the same reason, in the other direction.

        The engine's `#<name>.log` character log and config/debug.log are
        EVIDENCE and are committed on purpose -- the debug log is what
        makes the no-cheating claim auditable rather than asserted.
        """
        self.assertNotIn("*.log", self.hygiene_names())

    def test_an_in_repository_runtime_root_is_refused(self):
        """M-21: the root cause, refused at the irreversible act.

        env.sh refuses a nominated runtime root inside the checkout at
        source time, and this is the same rule applied where breaking it
        does permanent damage.  Asserted on the script's own text because
        env.sh's refusal fires first in a real run -- which is the
        correct order and also means the second control would otherwise
        never be exercised.
        """
        source = self.script_source()
        start = source.index("assert_runtime_root_is_outside() {")
        end = source.index("assert_no_machine_files() {", start)
        body = source[start:end]
        self.assertIn("playthrough_path_within", body)
        # Both directions: inside the repository, and containing it.
        self.assertEqual(body.count("playthrough_path_within"), 2)
        self.assertIn("EX_SCOPE", body)
        # And it is called before anything is staged.
        staging = source.index("assert_no_machine_files() {")
        self.assertIn("assert_runtime_root_is_outside",
                      source[staging:staging + 200])


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

    def test_the_capture_population_is_never_a_shell_array(self):
        """One capture per keystroke, and no list of them anywhere.

        The argv handed to git was already bounded; what was not was the
        two arrays built before it -- the find output read into one, then
        copied into a second inside the batcher.  A session length is
        deliberately unbounded, so the population is streamed instead:
        read, judged and written out one path at a time.
        """
        with open(os.path.join(TOOLING, SCRIPT_NAME),
                  encoding="utf-8") as handle:
            source = handle.read()
        self.assertNotIn("captures+=(", source,
                         msg="the captures are accumulated again")
        self.assertNotIn("present+=(", source,
                         msg="the staging list is accumulated again")
        self.assertIn("stage_stream()", source)
        self.assertIn("capture_pathspecs()", source)

    def test_the_captures_reach_git_as_one_pathspec_file(self):
        """One `git add`, so one index read and one index write.

        The index is the size of the repository rather than of the batch,
        so a call per 256 frames rewrote it once per 256 frames.  Given a
        NUL-delimited pathspec file, git takes the whole class at once.
        """
        with open(os.path.join(TOOLING, SCRIPT_NAME),
                  encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("--pathspec-from-file=", source)
        self.assertIn("--pathspec-file-nul", source)
        count = 12
        self.write_save()
        self.write_evidence(count)
        _, err = self.checkpoint("creation")
        self.assertIn("staged the captured frames: %d path(s)" % count,
                      err)
        self.assertEqual(len(self.tracked("playthrough/frames")), count)

    def test_a_git_without_pathspec_files_stages_every_capture(self):
        """The fallback, exercised by a git that refuses the option.

        The option pair arrived in git 2.25, so the streamed file is
        replayed in bounded chunks on anything older.  A wrapper that
        refuses it -- exactly as such a git does, with "unknown option"
        and a non-zero status -- proves the fallback stages the same
        population rather than merely existing in the source.
        """
        real = shutil.which("git")
        self.assertIsNotNone(real, msg="a real git is needed")
        marker = os.path.join(self.root, "pathspec-file-refused")
        self.write(
            os.path.join(self.bin, "git"),
            "#!/bin/sh\n"
            "for arg in \"$@\"; do\n"
            "    case \"${arg}\" in\n"
            "        --pathspec-from-file*)\n"
            "            printf 'refused\\n' >>%s\n"
            "            printf 'error: unknown option\\n' >&2\n"
            "            exit 129\n"
            "            ;;\n"
            "    esac\n"
            "done\n"
            "exec %s \"$@\"\n" % (marker, real),
            mode=0o755)
        with open(os.path.join(TOOLING, SCRIPT_NAME),
                  encoding="utf-8") as handle:
            bound = int(re.search(r"STAGE_BATCH_SIZE=(\d+)",
                                  handle.read()).group(1))
        count = bound + 3
        self.write_save()
        self.write_evidence(count)
        fields, err = self.checkpoint("creation")
        self.assertTrue(os.path.exists(marker),
                        msg="the capability was never probed, so the "
                            "fallback was not the path under test")
        self.assertEqual(fields["FRAMES"], str(count))
        self.assertIn("staged the captured frames: %d path(s)" % count,
                      err)
        self.assertEqual(len(self.tracked("playthrough/frames")), count)

    def test_frame_one_is_named_rather_than_searched_for(self):
        """The ignore probe needs one capture, so it names one.

        It used to `find` the whole directory and pipe it through `sort`,
        which cannot emit a line until it has read every one of them.
        """
        with open(os.path.join(TOOLING, SCRIPT_NAME),
                  encoding="utf-8") as handle:
            source = handle.read()
        body = re.search(r"^first_capture\(\) \{\n(.*?)^\}", source,
                         re.MULTILINE | re.DOTALL)
        self.assertIsNotNone(body)
        self.assertIn("FIRST_CAPTURE_BASENAME", body.group(1))
        self.assertNotIn('"${SORT}"', body.group(1))
        # And the name comes from env.sh's own capture format.
        self.assertIn('printf -v FIRST_CAPTURE_BASENAME -- '
                      '"${PLAYTHROUGH_FRAME_FORMAT}" 1', source)

    def test_the_emptiness_check_is_gits_own_boolean(self):
        """`diff --cached --quiet`, not a captured list of paths.

        Asking "is anything staged" by materialising one line per staged
        path is one line per capture to answer yes or no.
        """
        with open(os.path.join(TOOLING, SCRIPT_NAME),
                  encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("diff --cached --quiet HEAD", source)
        self.assertIn("anything_staged()", source)
        # The code, named exactly: the comment above the replacement
        # QUOTES the idiom it replaced, and a loose match would find the
        # explanation rather than a call.
        self.assertNotIn('if [ -z "$(staged_paths)" ]', source)
        self.assertNotIn('if [ -n "$(staged_paths_preview)" ]', source)
        # Every surviving reader of either one streams it.
        self.assertEqual(source.count("done < <(staged_paths)"), 1)
        self.assertEqual(
            source.count("done < <(staged_paths_preview)"), 2)

    def test_a_class_nobody_enumerated_is_refused_not_skipped(self):
        """Explicit staging's own failure mode, closed.

        A file directly under playthrough/ that no class names would
        otherwise be left behind in silence.  The refusal names it and
        says which list to add it to.

        IT IS NOW REFUSED BEFORE ANYTHING IS STAGED, and the exit code
        moved with it.  This used to be caught at the END, by the
        completeness sweep comparing the index against the tree -- which
        was the only place it could be caught while three whole
        directories were staged as subtree pathspecs.  Every path is
        classified up front now, so an unrecognised one costs a refusal
        (EX_SCOPE, a scope question) instead of being discovered after
        the staging it was left out of (EX_COMMIT).
        """
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        self.write(os.path.join(self.dir, "stray_artifact.txt"),
                   "nobody enumerated me\n")
        message = self.refuse(EX_SCOPE, ("creation",))
        self.assertIn("stray_artifact.txt", message)
        self.assertIn("belong to no artifact class", message)
        self.assertIn("classify_path", message)
        # And the index was not touched on the way out.
        self.assertEqual(
            "", self.git("diff", "--cached", "--name-only",
                         identity=False).strip())

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


class TestStagingIsAnAllowlistNotADenylist(CheckpointFixture):
    """What may be committed, and the inversion that decides it.

    Three of the classes used to be whole directories: `git add --
    playthrough/tooling`, `-- playthrough/userdir` and `--
    playthrough/build` staged whatever those trees happened to contain,
    and the only thing between an accident and a commit was a DENYLIST of
    the shapes somebody had already been bitten by -- bytecode, an ad-hoc
    test file, a quarantined film, the X authority cookie, a pid.

    A denylist answers "is this one of the bad things I know about".  A
    checkpoint has to answer "is this evidence".  Every artifact a future
    stage invents, every scratch file a debugging session leaves and every
    new cache the engine starts writing is admitted by the first question
    and refused by the second -- and .gitignore's terminal
    `!/playthrough/**` negation makes that worse rather than better,
    because "it would have been ignored" is not a fallback that exists
    inside this tree.
    """

    def refuse_over_path(self, relative, content="not evidence\n"):
        """Plant one path under playthrough/ and take a checkpoint."""
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        self.write(os.path.join(self.dir, relative), content)
        return self.refuse(EX_SCOPE, ("creation",))

    def test_an_unauthored_file_in_the_tooling_directory_is_refused(self):
        """The directory pathspec's blind spot, closed."""
        message = self.refuse_over_path("tooling/scratch_probe.py")
        self.assertIn("scratch_probe.py", message)
        self.assertIn("belong to no artifact class", message)

    def test_a_nested_path_under_tooling_is_refused(self):
        """One level, and one exception to it that is named explicitly."""
        message = self.refuse_over_path("tooling/nested/deep.py")
        self.assertIn("nested/deep.py", message)

    def test_an_unknown_build_intermediate_is_refused(self):
        message = self.refuse_over_path("build/scratch.txt")
        self.assertIn("build/scratch.txt", message)

    def test_a_mispadded_transition_frame_is_refused(self):
        """The schema is the five-and-two digits, not merely the prefix.

        A transition frame whose index is not zero-padded sorts wrongly in
        the concat list, so a name that only looks right is not right.
        """
        message = self.refuse_over_path("build/transitions/trans_1_1.png")
        self.assertIn("trans_1_1.png", message)

    def test_a_mispadded_capture_is_refused(self):
        """By the capture gates, which answer sooner and say more.

        A stray file in frames/ breaks the one-frame-per-keystroke
        identity before the classification is ever reached, so the
        refusal is an EVIDENCE question rather than a scope one -- which
        is the right order: "the captures and the record disagree" tells
        an operator what is wrong with the recording, where "this belongs
        to no artifact class" would only tell them something is in the
        way.  The classifier refuses the same name independently, which
        the sibling test over the real tree covers.
        """
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        self.write(os.path.join(self.dir, "frames/frame_7.png"),
                   "not a capture\n")
        message = self.refuse(EX_EVIDENCE, ("creation",))
        # It reports the arithmetic rather than the filename, which is
        # the more useful half: the count is what proves the identity
        # broke, and an operator who sees "5 captures against 4 rows"
        # knows to look for the extra file.
        self.assertIn("One keystroke is one capture is one row", message)
        self.assertIn("5 capture(s)", message)

    def test_a_file_outside_the_engines_subtrees_is_refused(self):
        """Position is the schema for the engine's tree.

        The cookie is the case that matters: env.sh keeps the runtime root
        outside the checkout precisely so it cannot be staged, and the
        terminal negation means one that landed here anyway would be
        committable -- and a credential in a published commit cannot be
        withdrawn, only rotated.
        """
        message = self.refuse_over_path("userdir/Xauthority", "a cookie\n")
        self.assertIn("userdir/Xauthority", message)

    def test_the_index_is_untouched_by_the_refusal(self):
        """It runs before staging, so there is nothing to undo."""
        self.refuse_over_path("build/scratch.txt")
        self.assertEqual(
            "", self.git("diff", "--cached", "--name-only",
                         identity=False).strip())

    def test_the_engines_own_filenames_are_accepted_by_position(self):
        """A shape nobody enumerated, in a place the engine owns.

        The engine writes names this pipeline does not choose --
        `#<b64>.ano.json`, `.pt`, `.seen.0.-1`, `.zones.json`,
        `10.5.0.mmr` memory regions, `<name>-<serial>.json.-46513.fb`
        caches -- so a per-FILENAME allowlist over its output would refuse
        a correct checkpoint the first time a new engine version wrote a
        new one.  What is pinned is where it may write, and this test is
        the proof that the distinction is real: an invented extension in a
        legitimate subtree is accepted.
        """
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        for relative in (
                "userdir/save/%s/#abc.some-future-extension" % WORLD,
                "userdir/cache/whatever-9999.fb",
                "userdir/memorial/%s/10.5.0.mmr" % WORLD,
                "userdir/templates/Last Character.template"):
            self.write(os.path.join(self.dir, relative), "engine bytes\n")
        fields, _ = self.checkpoint("creation")
        self.assertEqual(fields["COMMITTED"], "yes")

    def test_every_authored_tooling_file_in_the_tree_is_accepted(self):
        """The acceptance direction, over the real repository.

        A gate that refuses nothing is useless and a gate that refuses
        everything is worse, so the allowlist is read against the actual
        checkout: every file this feature really ships has to classify.
        """
        names = sorted(name for name in os.listdir(TOOLING)
                       if os.path.isfile(os.path.join(TOOLING, name)))
        self.assertGreater(len(names), 30,
                           msg="the real tooling directory was not read")
        source = self.script_source()
        for name in names:
            with self.subTest(name=name):
                if name.startswith("test_") and name.endswith(".py"):
                    continue
                self.assertIn(
                    '"%s"' % name, source,
                    msg=("%s ships in playthrough/tooling/ and no class "
                         "names it, so a checkpoint would refuse the "
                         "whole tree" % name))


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


class TestTheDossierCheckpoint(CheckpointFixture):
    """The first of the three commits, and why it has to be its own.

    The requirement is that the survivor's dossier is written and
    committed BEFORE the first gameplay frame, and "before" is a
    statement about ancestry.  A single commit carrying both the dossier
    and frame_00001 cannot satisfy it, because one commit does not
    precede itself -- which is exactly the state the acceptance gate
    found in the real history and reported as unprovable.  Splitting the
    dossier out is what makes the ordering readable from the history at
    all.
    """

    def test_it_commits_the_dossier_and_its_seal(self):
        """The dossier, and the one thing that vouches for it.

        THE EVIDENCE ANCHOR TRAVELS WITH IT, and that is the point of the
        anchor rather than a leak in this checkpoint's scope.  The
        requirement being satisfied here is that the dossier was written
        before play, and the whole force of it rests on the dossier's
        bytes not having changed since.  So this checkpoint seals those
        bytes -- by sha256 and by git's own blob name -- and publishes the
        chain's head in its own message, in the same commit.  Committing
        the dossier without its seal would leave the earliest and most
        order-sensitive artifact in the tree as the only one nothing
        vouches for.
        """
        self.forget_dossier()
        fields, _ = self.take_dossier()
        self.assertEqual(fields["COMMITTED"], "yes")
        self.assertEqual(self.touched_by(),
                         ["playthrough/build/evidence_anchor.jsonl",
                          "playthrough/dossier.md"])

    def test_the_dossiers_own_bytes_are_what_it_seals(self):
        """Nothing else exists yet, so the seal is exactly one row."""
        self.forget_dossier()
        self.take_dossier()
        path = os.path.join(self.checkout, "playthrough", "build",
                            "evidence_anchor.jsonl")
        with open(path, "r", encoding="utf-8") as handle:
            rows = [json.loads(line) for line in handle if line.strip()]
        self.assertEqual([row["path"] for row in rows], ["dossier.md"])
        self.assertEqual(
            rows[0]["git_blob"],
            self.git("rev-parse", "HEAD:playthrough/dossier.md",
                     identity=False).strip())

    def test_it_carries_its_own_trailer(self):
        self.forget_dossier()
        self.take_dossier()
        self.assertIn("Playthrough-Checkpoint: dossier", self.message())

    def test_the_ordering_it_establishes_is_readable_afterwards(self):
        """The property the whole split exists for, read out of git."""
        self.forget_dossier()
        dossier, _ = self.take_dossier()
        self.take_creation()
        frame = self.introduced("playthrough/frames/frame_00001.png")
        self.assertNotEqual(dossier["COMMIT"], frame)
        self.git("merge-base", "--is-ancestor", dossier["COMMIT"], frame,
                 identity=False)

    def test_it_is_refused_once_a_capture_is_tracked(self):
        """Taken late it would prove nothing, so it is not allowed to
        look like it worked."""
        self.take_creation()
        message = self.refuse(EX_LIFECYCLE, ("dossier",))
        self.assertIn("already", message)
        self.assertIn("could not put the dossier ahead", message)

    def test_a_missing_dossier_is_refused(self):
        os.unlink(os.path.join(self.dir, "dossier.md"))
        self.refuse(EX_EVIDENCE, ("dossier",))

    def test_a_re_run_commits_nothing_and_says_so(self):
        self.forget_dossier()
        self.take_dossier()
        before = self.head()
        fields, err = self.checkpoint("dossier")
        self.assertEqual(fields["COMMITTED"], "no")
        self.assertEqual(before, self.head())
        self.assertIn("already", err)


class TestTheDossierRefusesOnceTheSessionHasBegun(CheckpointFixture):
    """"Before the first gameplay frame" is about events, not commits.

    THE COUNT USED TO BE OF TRACKED CAPTURES ONLY, which asks whether the
    frames were COMMITTED rather than whether they EXIST.  On the ordinary
    post-session tree -- every frame written, the record appended, nothing
    committed yet -- that count is zero, so the refusal never fired and a
    dossier commit taken there claimed to precede a session that had
    already been played and whose frames were sitting on the disk beside
    it.  The ordering would then read correctly out of git while being
    false about the world, which is the worst kind of passing evidence.

    So the question is now whether the session left ANY trace, wherever
    that trace is: a capture on disk, a capture in the index, a manifest
    row, a sidecar observation, or a capture attestation.  Each of these
    tests supplies exactly ONE of them, because a gate that only fires
    when several are present is a gate with a gap in it.
    """

    def refuse_dossier(self):
        message = self.refuse(EX_LIFECYCLE, ("dossier",))
        self.assertIn("the session has already left evidence", message)
        return message

    def test_an_uncommitted_capture_on_disk_is_enough(self):
        """The case that used to walk straight through."""
        self.write(
            os.path.join(self.frames_dir, "frame_00001.png"),
            "a frame that was captured but never committed\n")
        self.assertFalse(
            self.is_tracked("playthrough/frames/frame_00001.png"),
            msg="the fixture was supposed to leave it untracked")
        message = self.refuse_dossier()
        self.assertIn("1 capture(s) on disk", message)

    def test_a_manifest_row_is_enough(self):
        with open(self.manifest, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(self.row(1)) + "\n")
        message = self.refuse_dossier()
        self.assertIn("row(s) in playthrough/manifest.jsonl", message)

    def test_a_sidecar_observation_is_enough(self):
        """The capture stage appends one of these per frame, so it is a
        trace of play even where the frame itself was cleaned up."""
        with open(self.observations, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(self.observation(1)) + "\n")
        message = self.refuse_dossier()
        self.assertIn("observations.jsonl", message)

    def test_a_capture_attestation_is_enough(self):
        with open(self.digests, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "frame": 1,
                "file": "playthrough/frames/frame_00001.png",
                "sha256": "0" * 64,
                "bytes": 1,
                "attested": "capture",
                "attested_ts": "2026-08-04T06:53:01.429Z",
                "git_blob": None,
                "git_commit": None,
            }) + "\n")
        message = self.refuse_dossier()
        self.assertIn("frame_digests.jsonl", message)

    def test_the_refusal_says_the_ordering_cannot_be_backdated(self):
        """The operator needs to know that there is no way to fix this
        by committing harder."""
        self.write(os.path.join(self.frames_dir, "frame_00001.png"),
                   "a frame\n")
        message = self.refuse_dossier()
        self.assertIn("cannot be established after the fact", message)
        self.assertIn("re-recorded", message)

    def test_a_tree_where_play_has_not_begun_is_still_allowed(self):
        """The positive control: the gate must not be unconditional."""
        self.forget_dossier()
        fields, _ = self.checkpoint("dossier")
        self.assertEqual(fields["COMMITTED"], "yes")
        # The dossier and the seal that binds its bytes; see
        # TestTheDossierCheckpoint for why the two travel together.
        self.assertEqual(self.touched_by(),
                         ["playthrough/build/evidence_anchor.jsonl",
                          "playthrough/dossier.md"])


class TestTheOrderingIsAboutThisGeneration(CheckpointFixture):
    """WHICH commits are compared, and why the oldest ones are the wrong
    answer.

    The reading used to be "the oldest commit that ever touched this
    path", which is a fact about the PATH rather than about the recording
    now in the tree.  These paths are reused by every generation:
    `playthrough/dossier.md` and `playthrough/frames/frame_00001.png` are
    the same two names for every survivor who is ever recorded here.  So
    a retired session that happened to be committed in the right order
    left an ordering behind that a later, wholly differently ordered
    recording then inherited -- and the requirement being asserted is
    about the survivor whose words and whose first frame are in the tree
    NOW.

    The reading is therefore the NEWEST commit that changed each path,
    which is by definition the commit that produced the content HEAD
    carries.
    """

    def run_final(self):
        """Take `final` and return (status, message) without asserting.

        The ordering is verified from the history the commit MADE, so a
        violation is reported after that commit exists -- deliberately,
        because the final commit itself can be the thing that rewrites
        the dossier, and a check that ran earlier would not see it.  That
        is why this cannot use `refuse`, which asserts HEAD did not move.
        """
        status, out, err = self.run_script(("final",))
        return status, err + out

    def test_a_correctly_ordered_generation_passes(self):
        """The control, and the message names both commits it compared."""
        self.forget_dossier()
        dossier, _ = self.take_dossier()
        self.take_creation()
        self.play_session()
        _, err = self.checkpoint("final")
        self.assertIn("strict ancestor", err)
        self.assertIn(dossier["COMMIT"][:10], err)

    def test_a_dossier_rewritten_after_the_session_is_refused(self):
        """The regression this reading exists for.

        Under the old measurement this history PASSED: the dossier's
        oldest commit was the dossier checkpoint, taken before any frame,
        so the ancestry held -- while the words actually in the tree were
        written after the session was over and were published by the
        final commit itself.
        """
        self.forget_dossier()
        self.take_dossier()
        self.take_creation()
        self.play_session()
        self.write(os.path.join(self.dir, "dossier.md"),
                   "# %s\n\nRewritten with hindsight.\n" % CHARACTER)
        status, message = self.run_final()
        self.assertEqual(
            status, EX_COMMIT,
            msg="a dossier rewritten after the session was accepted:\n%s"
                % message)
        self.assertIn("not an ancestor", message)
        self.assertIn("REWRITTEN after the session was captured",
                      message)

    def test_a_bundled_generation_cannot_inherit_an_ordering(self):
        """One commit carrying both cannot precede itself, even where an
        earlier generation of these paths was ordered correctly.
        """
        self.forget_dossier()
        self.take_dossier()
        self.take_creation()
        self.play_session()
        self.checkpoint("final")
        # A second generation, published the way the real history was:
        # the survivor's words and the first frame in ONE commit.  The
        # first generation's ordering is still in this history, and is
        # still no help to this one.
        self.write(os.path.join(self.dir, "dossier.md"),
                   "# %s\n\nA second survivor entirely.\n" % CHARACTER)
        self.write(os.path.join(self.frames_dir, "frame_00001.png"),
                   "a capture from the second recording\n")
        self.git("add", "--", "playthrough/dossier.md",
                 "playthrough/frames/frame_00001.png")
        self.git("commit", "--quiet", "-m",
                 "Publish a second recording in one bundle")
        self.write_digests(self.CREATION_ROWS + self.SESSION_ROWS)
        self.write_save(revision="a second closing save")
        status, message = self.run_final()
        self.assertEqual(
            status, EX_COMMIT,
            msg="a bundled generation inherited an ordering:\n%s"
                % message)
        self.assertIn("put BOTH the current", message)
        self.assertIn("cannot precede itself", message)

    def test_the_reading_is_the_newest_commit_not_the_oldest(self):
        """Read off the source, because the whole finding was that these
        two questions look alike and are not."""
        with open(os.path.join(TOOLING, SCRIPT_NAME),
                  encoding="utf-8") as handle:
            source = handle.read()
        self.assertTrue(
            "generation_commit() answers the question that matters"
            in source,
            msg="the generation reading is gone")
        self.assertTrue(
            "log --max-count=1 --format=%H HEAD --" in source,
            msg="the ordering is no longer read from the newest commit "
                "that changed the path")


class TestTheIntegrationMilestone(CheckpointFixture):
    """The one milestone that commits something outside playthrough/.

    THE TWO RULE FILES HAD NO COMMITTER AT ALL.  Every checkpoint checked
    them -- the terminal negation in `.gitignore` and the attribute rows in
    `.gitattributes` -- and every checkpoint refused to stage them, on
    the reasoning that repository-wide configuration does not belong in a
    commit about a survivor.  That reasoning is right and the conclusion
    was incomplete: the plan requires both files to be MODIFIED and
    COMMITTED, and a negation that was never committed loses the save
    data on the next fresh clone while every working-tree check still
    passes.  So the two files get a milestone of their own, scoped to
    exactly them.
    """

    def edited_ignore(self):
        """A .gitignore that differs from HEAD and is still correct.

        The comment goes ABOVE the negation, because the negation has to
        remain the last effective rule -- which is the property the
        milestone refuses to publish without.
        """
        return SANDBOX_GITIGNORE.replace(
            NEGATION_LINE, "# an operator's note\n" + NEGATION_LINE)

    def edit_both_rule_files(self):
        self.write(self.gitignore, self.edited_ignore())
        self.write(os.path.join(self.checkout, ".gitattributes"),
                   SANDBOX_GITATTRIBUTES + "*.ogg binary\n")

    def test_it_commits_exactly_the_two_rule_files(self):
        self.edit_both_rule_files()
        fields, _ = self.checkpoint("integration")
        self.assertEqual(fields["COMMITTED"], "yes")
        self.assertEqual(self.touched_by(),
                         [".gitattributes", ".gitignore"])

    def test_it_leaves_the_artifact_tree_alone(self):
        """Scoped BOTH ways: this milestone is not a shortcut for the
        session checkpoints either."""
        self.write(self.gitignore, self.edited_ignore())
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        self.checkpoint("integration")
        self.assertEqual(self.touched_by(), [".gitignore"])
        self.assertFalse(
            self.is_tracked("playthrough/frames/frame_00001.png"),
            msg="the integration milestone published a capture")

    def test_its_message_names_the_files_and_nothing_it_did_not_do(self):
        self.edit_both_rule_files()
        self.checkpoint("integration")
        message = self.message()
        self.assertIn("- .gitignore", message)
        self.assertIn("- .gitattributes", message)
        self.assertIn("Playthrough-Checkpoint: integration", message)
        self.assertNotIn(CHARACTER, message)
        self.assertNotIn("keystroke(s) captured", message)

    def test_a_re_run_manufactures_no_empty_commit(self):
        """HEAD already carrying them is the ordinary state, not a
        failure, and it must not produce a commit that records nothing.
        """
        self.edit_both_rule_files()
        self.checkpoint("integration")
        before = self.head()
        fields, err = self.checkpoint("integration")
        self.assertEqual(fields["COMMITTED"], "no")
        self.assertEqual(before, self.head())
        self.assertIn("No empty commit was manufactured", err)

    def test_it_needs_no_evidence_and_no_save(self):
        """It runs FIRST, before a survivor exists at all, so it cannot
        be gated on any artifact."""
        self.edit_both_rule_files()
        self.assertFalse(os.path.exists(self.manifest))
        self.assertFalse(os.path.exists(self.master))
        fields, _ = self.checkpoint("integration")
        self.assertEqual(fields["COMMITTED"], "yes")

    def test_staged_artifact_work_is_refused(self):
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        self.git("add", "--", "playthrough/manifest.jsonl")
        self.write(self.gitignore, self.edited_ignore())
        message = self.refuse(EX_SCOPE, ("integration",))
        self.assertIn("neither .gitignore nor .gitattributes", message)
        self.assertIn("playthrough/manifest.jsonl", message)
        self.assertIn("publishes the whole index", message)

    def test_a_working_tree_negation_that_is_not_last_is_refused(self):
        """It publishes these rules, so it will not publish them broken.

        A rule after the negation re-excludes what the negation rescued,
        and committing that is precisely the silent failure the whole
        block exists to prevent.
        """
        self.write(self.gitignore,
                   SANDBOX_GITIGNORE + "playthrough/frames\n")
        message = self.refuse(EX_PREREQ, ("integration",))
        self.assertIn("not '%s'" % NEGATION_LINE, message)
        self.assertIn("Nothing was committed", message)

    def test_a_working_tree_missing_an_attribute_row_is_refused(self):
        for row in REQUIRED_ATTRIBUTE_ROWS:
            with self.subTest(row=row):
                self.write(
                    os.path.join(self.checkout, ".gitattributes"),
                    SANDBOX_GITATTRIBUTES.replace(row + "\n", ""))
                message = self.refuse(EX_PREREQ, ("integration",))
                self.assertIn("carries no '%s' row" % row, message)

    def test_the_published_rules_are_asserted_from_the_history(self):
        """The point of the commit, read back out of the commit."""
        self.edit_both_rule_files()
        _, err = self.checkpoint("integration")
        self.assertIn("HEAD's own .gitignore", err)
        self.assertIn(NEGATION_LINE, err)

    def test_it_is_the_only_milestone_that_reaches_outside(self):
        """Read off the source: one declared list, two names in it."""
        with open(os.path.join(TOOLING, SCRIPT_NAME),
                  encoding="utf-8") as handle:
            source = handle.read()
        self.assertTrue(
            'INTEGRATION_PATHS=(".gitignore" ".gitattributes")'
            in source,
            msg="the milestone's scope is no longer two declared names")


class TestCreationRequiresATrackedDossier(CheckpointFixture):
    """The refusal that keeps the two out of one commit.

    Without it the narrative class and the captures are staged together,
    the dossier and frame_00001 share an introducing commit, and the
    before-play ordering becomes permanently unprovable -- not fixable
    later, because the only remedy is rewriting history.
    """

    def test_creation_before_the_dossier_is_committed_is_refused(self):
        self.forget_dossier()
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        message = self.refuse(EX_LIFECYCLE, ("creation",))
        self.assertIn("not", message)
        self.assertIn("one commit cannot precede itself", message)

    def test_the_refusal_names_the_subcommand_that_fixes_it(self):
        self.forget_dossier()
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        message = self.refuse(EX_LIFECYCLE, ("creation",))
        self.assertIn("commit_artifacts.sh dossier", message)

    def test_creation_proceeds_once_the_dossier_is_in_the_history(self):
        self.forget_dossier()
        self.take_dossier()
        fields, _ = self.take_creation()
        self.assertEqual(fields["COMMITTED"], "yes")


class TestTheLifecycleIsAnchoredOnTheSurvivor(CheckpointFixture):
    """A row count cannot tell two survivors apart.

    The check `final` used to make was that the record had more rows than
    at the `creation` checkpoint.  A session RE-RECORDED FROM SCRATCH
    passes that: its record grew from nothing too.  So a `final` was
    accepted whose anchoring `creation` commit described a different
    person entirely, and the history ended up with lifecycle commits
    naming a survivor who is not the one in the save -- which is the
    divergence the acceptance gate found and cannot repair without
    rewriting history.

    The anchor is now resolved by survivor: a `creation` checkpoint whose
    tree names THIS world and character.  When none exists, the refusal
    names both survivors rather than reporting an arithmetic result.
    """

    OTHER_WORLD = "Apshawa"
    OTHER_CHARACTER = "Ambrose Halloran"
    # base64 of the name above, which is how the engine spells the file.
    OTHER_SAVE = "#QW1icm9zZSBIYWxsb3Jhbg==.sav"

    def become_the_other_survivor(self):
        """Replace the save with a different survivor's, as a re-record
        would: the previous world's files are gone, not kept beside it."""
        shutil.rmtree(self.world_dir)
        other_dir = os.path.join(self.dir, "userdir", "save",
                                 self.OTHER_WORLD)
        self.write(os.path.join(other_dir, "master.gsav"),
                   "master state (a different survivor)\n")
        self.write(os.path.join(other_dir, self.OTHER_SAVE),
                   "character state (a different survivor)\n")
        self.write(self.lastworld,
                   json.dumps({"world_name": self.OTHER_WORLD,
                               "character_name": self.OTHER_CHARACTER},
                              indent=2) + "\n")

    def test_a_final_for_another_survivor_is_refused(self):
        self.take_creation()
        self.become_the_other_survivor()
        self.write_evidence(self.CREATION_ROWS + self.SESSION_ROWS)
        message = self.refuse(EX_LIFECYCLE, ("final",))
        self.assertIn(CHARACTER, message)
        self.assertIn(self.OTHER_CHARACTER, message)

    def test_the_refusal_explains_why_a_row_count_is_not_enough(self):
        self.take_creation()
        self.become_the_other_survivor()
        self.write_evidence(self.CREATION_ROWS + self.SESSION_ROWS)
        message = self.refuse(EX_LIFECYCLE, ("final",))
        self.assertIn("row count cannot tell the two apart", message)

    def test_the_new_survivor_may_take_a_creation_of_their_own(self):
        """The other half of the fix, and the reason the refusal above is
        not simply a dead end.

        The unscoped check ALSO refused a new survivor's `creation`
        whenever any previous recording had one, which is precisely how a
        re-recorded session ended up with no checkpoint of its own.
        """
        self.take_creation()
        self.become_the_other_survivor()
        self.write_evidence(self.CREATION_ROWS + self.SESSION_ROWS)
        fields, _ = self.checkpoint("creation")
        self.assertEqual(fields["COMMITTED"], "yes")
        self.assertEqual(fields["CHARACTER"], self.OTHER_CHARACTER)

    def test_the_anchor_that_is_found_is_reported(self):
        self.take_creation()
        self.play_session()
        _, err = self.checkpoint("final")
        self.assertIn(CHARACTER, err)
        self.assertIn("creation", err)

    def test_status_warns_when_the_newest_creation_is_someone_else(self):
        """`status` reads and reports; it never refuses."""
        self.take_creation()
        self.become_the_other_survivor()
        status, out, err = self.run_script(("status",))
        self.assertEqual(status, EX_OK)
        fields = self.payload(out)
        self.assertEqual(fields["CHARACTER"], self.OTHER_CHARACTER)
        self.assertIn(CHARACTER, fields["CREATION_SURVIVOR"])
        self.assertIn("WARNING", err)


class TestTheEligibilityAnswer(CheckpointFixture):
    """Would `final` be taken?  Asked without taking it.

    Every expensive stage of the post-session pipeline runs BEFORE the
    checkpoint, so a checkpoint that is going to refuse should say so
    first: the sequencer reads this answer ahead of its first stage and
    stops there instead of spending the timeline, the transitions, the
    encode, the transcripts, the caption mux and the whole functional
    gate to be refused at the end.

    The answer is computed with the same two predicates the refusal
    enforces -- the survivor-specific anchor and the row growth since it
    -- so it cannot drift from what it predicts.  That mattered
    immediately: `status` used to compare against the NEWEST creation
    checkpoint, which is not the one `final` anchors to, and therefore
    reported a refusal for a session whose own anchor was simply an
    older commit.
    """

    OTHER_WORLD = "Apshawa"
    OTHER_CHARACTER = "Ambrose Halloran"
    OTHER_SAVE = "#QW1icm9zZSBIYWxsb3Jhbg==.sav"

    def become_the_other_survivor(self):
        """The save of a different survivor, as a re-record leaves it."""
        shutil.rmtree(self.world_dir)
        other_dir = os.path.join(self.dir, "userdir", "save",
                                 self.OTHER_WORLD)
        self.write(os.path.join(other_dir, "master.gsav"),
                   "master state (a different survivor)\n")
        self.write(os.path.join(other_dir, self.OTHER_SAVE),
                   "character state (a different survivor)\n")
        self.write(self.lastworld,
                   json.dumps({"world_name": self.OTHER_WORLD,
                               "character_name": self.OTHER_CHARACTER},
                              indent=2) + "\n")

    def become_the_original_survivor(self):
        """Back to the first survivor, whose creation is now OLDER."""
        shutil.rmtree(os.path.join(self.dir, "userdir", "save",
                                   self.OTHER_WORLD))
        self.write_save(revision="resumed")

    def answer(self):
        """The three eligibility keys `status` reports."""
        status, out, err = self.run_script(("status",))
        self.assertEqual(status, EX_OK, msg=err)
        fields = self.payload(out)
        for key in ("FINAL_ELIGIBLE", "FINAL_ANCHOR", "FINAL_REASON"):
            self.assertIn(key, fields)
        return fields

    def test_a_session_ready_for_its_checkpoint_answers_yes(self):
        creation, _ = self.take_creation()
        self.play_session()
        fields = self.answer()
        self.assertEqual(fields["FINAL_ELIGIBLE"], "yes")
        self.assertEqual(fields["FINAL_ANCHOR"], creation["COMMIT"])
        self.assertEqual(fields["FINAL_REASON"], "")

    def test_the_answer_predicts_what_the_checkpoint_then_does(self):
        """The two must agree, which is the whole point of one rule."""
        self.take_creation()
        self.play_session()
        self.assertEqual(self.answer()["FINAL_ELIGIBLE"], "yes")
        fields, _ = self.checkpoint("final")
        self.assertEqual(fields["COMMITTED"], "yes")

    def test_no_creation_at_all_is_named_as_such(self):
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        fields = self.answer()
        self.assertEqual(fields["FINAL_ELIGIBLE"], "no")
        self.assertEqual(fields["FINAL_REASON"], "no-creation-checkpoint")
        self.assertEqual(fields["FINAL_ANCHOR"], "")

    def test_a_creation_for_somebody_else_is_named_as_such(self):
        self.take_creation()
        self.become_the_other_survivor()
        self.write_evidence(self.CREATION_ROWS + self.SESSION_ROWS)
        fields = self.answer()
        self.assertEqual(fields["FINAL_ELIGIBLE"], "no")
        self.assertEqual(fields["FINAL_REASON"],
                         "no-creation-for-this-survivor")

    def test_a_record_that_has_not_grown_is_named_as_such(self):
        self.take_creation()
        self.write_save(revision="reopened but unplayed")
        fields = self.answer()
        self.assertEqual(fields["FINAL_ELIGIBLE"], "no")
        self.assertEqual(fields["FINAL_REASON"], "record-has-not-grown")

    def test_a_session_with_no_survivor_loaded_is_named_as_such(self):
        self.write_evidence(self.CREATION_ROWS)
        fields = self.answer()
        self.assertEqual(fields["FINAL_ELIGIBLE"], "no")
        self.assertEqual(fields["FINAL_REASON"], "no-survivor-loaded")

    def test_an_older_anchor_is_found_rather_than_reported_missing(self):
        """THE IMPRECISION THIS FIXES, driven end to end.

        Two creation checkpoints exist and the newest is somebody else's,
        but this session's own anchor is the OLDER one -- so `final` will
        anchor to it and succeed.  Comparing against the newest, as
        `status` used to, answers "would REFUSE" for a run that is
        perfectly eligible, which is exactly the false alarm a preflight
        must not raise.
        """
        first, _ = self.take_creation()
        self.become_the_other_survivor()
        self.write_evidence(self.CREATION_ROWS + 1)
        second, _ = self.checkpoint("creation")
        self.assertEqual(second["COMMITTED"], "yes")
        self.become_the_original_survivor()
        self.write_evidence(self.CREATION_ROWS + self.SESSION_ROWS)
        fields = self.answer()
        self.assertEqual(fields["CREATION"], second["COMMIT"])
        self.assertEqual(fields["FINAL_ANCHOR"], first["COMMIT"])
        self.assertEqual(fields["FINAL_ELIGIBLE"], "yes")
        # And the prediction holds when the checkpoint is really taken.
        taken, _ = self.checkpoint("final")
        self.assertEqual(taken["COMMITTED"], "yes")
        self.assertEqual(taken["CREATION"], first["COMMIT"])

    def test_the_report_says_which_answer_it_gave(self):
        self.take_creation()
        self.play_session()
        _, _, err = self.run_script(("status",))
        self.assertIn("is eligible", err)
        self.write_evidence(self.CREATION_ROWS)
        _, _, err = self.run_script(("status",))
        self.assertIn("would REFUSE", err)

    def test_the_answer_changes_nothing(self):
        """A preflight that committed would be worse than none."""
        self.take_creation()
        self.play_session()
        before = self.head()
        self.answer()
        self.assertEqual(before, self.head())
        self.assertEqual(
            "", self.git("diff", "--cached", "--name-only",
                         identity=False).strip())


class TestTheMediaEligibilityAnswer(CheckpointFixture):
    """Would `media` be taken?  A DIFFERENT question, asked as well.

    run_pipeline.sh takes `media`, not `final`: the film, the transcripts
    and the timeline are what a render produces, and the session's own
    save was committed by hand when the session closed.  `media`
    therefore asserts something `final` does not -- that a `final` for
    THIS survivor is already in the history -- and a preflight reporting
    only FINAL_ELIGIBLE answered `yes` for a session whose save had not
    been committed yet, which let the caller spend the timeline, the
    encode, both transcripts and the whole functional gate to be refused
    at the checkpoint.  That is the exact failure a preflight exists to
    prevent, so the question is answered here too, with the same
    predicate the refusal uses.
    """

    OTHER_WORLD = "Apshawa"
    OTHER_CHARACTER = "Ambrose Halloran"
    OTHER_SAVE = "#QW1icm9zZSBIYWxsb3Jhbg==.sav"

    def become_the_other_survivor(self):
        """The save of a different survivor, as a re-record leaves it."""
        shutil.rmtree(self.world_dir)
        other_dir = os.path.join(self.dir, "userdir", "save",
                                 self.OTHER_WORLD)
        self.write(os.path.join(other_dir, "master.gsav"),
                   "master state (a different survivor)\n")
        self.write(os.path.join(other_dir, self.OTHER_SAVE),
                   "character state (a different survivor)\n")
        self.write(self.lastworld,
                   json.dumps({"world_name": self.OTHER_WORLD,
                               "character_name": self.OTHER_CHARACTER},
                              indent=2) + "\n")

    def answer(self):
        """The three media keys, and the three final keys beside them."""
        status, out, err = self.run_script(("status",))
        self.assertEqual(status, EX_OK, msg=err)
        fields = self.payload(out)
        for key in ("MEDIA_ELIGIBLE", "MEDIA_ANCHOR", "MEDIA_REASON"):
            self.assertIn(key, fields)
        return fields

    def test_a_closed_and_committed_session_answers_yes(self):
        self.take_creation()
        self.play_session()
        final, _ = self.checkpoint("final")
        self.assertEqual(final["COMMITTED"], "yes")
        fields = self.answer()
        self.assertEqual(fields["MEDIA_ELIGIBLE"], "yes")
        self.assertEqual(fields["MEDIA_ANCHOR"], final["COMMIT"])
        self.assertEqual(fields["MEDIA_REASON"], "")

    def test_a_session_not_yet_committed_answers_no(self):
        """THE DIVERGENCE THAT MATTERS, measured in one run.

        `final` is eligible -- the anchor is this survivor's and the
        record has grown -- while `media` is not, because that `final`
        has not been taken.  A caller reading the wrong triple gets
        `yes` here and a refusal an hour later.
        """
        self.take_creation()
        self.play_session()
        fields = self.answer()
        self.assertEqual(fields["FINAL_ELIGIBLE"], "yes")
        self.assertEqual(fields["MEDIA_ELIGIBLE"], "no")
        self.assertEqual(fields["MEDIA_REASON"], "no-final-published")
        self.assertEqual(fields["MEDIA_ANCHOR"], "")

    def test_the_answer_predicts_what_the_checkpoint_then_does(self):
        """Both directions, because a preflight is only worth its word."""
        self.take_creation()
        self.play_session()
        self.assertEqual(self.answer()["MEDIA_ELIGIBLE"], "no")
        self.refuse(EX_LIFECYCLE, ("media",))
        self.checkpoint("final")
        self.assertEqual(self.answer()["MEDIA_ELIGIBLE"], "yes")
        self.write_media()
        fields, _ = self.checkpoint("media")
        self.assertEqual(fields["COMMITTED"], "yes")

    def test_no_anchor_at_all_repeats_the_reason_final_gave(self):
        """With no creation there is no ancestry to ask about."""
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        fields = self.answer()
        self.assertEqual(fields["MEDIA_ELIGIBLE"], "no")
        self.assertEqual(fields["MEDIA_REASON"],
                         "no-creation-checkpoint")
        self.assertEqual(fields["MEDIA_ANCHOR"], "")

    def test_another_survivors_final_does_not_satisfy_it(self):
        """Ancestry, not the trailer, is what decides "this session".

        Retiring a superseded recording deletes files; it does not
        rewrite history, so that recording's own `final` is still
        reachable from HEAD.  A carve-out phrased as "some reachable
        final" would be satisfied by somebody else's session.
        """
        self.take_creation()
        self.play_session()
        self.checkpoint("final")
        # A second survivor, whose own creation is newer and who has no
        # final of their own.  The first survivor's final is reachable
        # but is not a descendant of THIS creation.  The record only ever
        # GROWS here: write_evidence writes as many frames as rows and
        # removes none, so a smaller count would leave captures with no
        # row and be refused by the 1:1 invariant before the lifecycle
        # was reached at all.  Measured.
        self.become_the_other_survivor()
        self.write_evidence(self.CREATION_ROWS + self.SESSION_ROWS + 1)
        self.checkpoint("creation")
        self.write_evidence(self.CREATION_ROWS + self.SESSION_ROWS + 2)
        fields = self.answer()
        self.assertEqual(fields["MEDIA_ELIGIBLE"], "no")
        self.assertEqual(fields["MEDIA_REASON"], "no-final-published")

    def test_the_report_says_which_answer_it_gave(self):
        self.take_creation()
        self.play_session()
        _, _, err = self.run_script(("status",))
        self.assertIn("'media' would REFUSE", err)
        self.checkpoint("final")
        _, _, err = self.run_script(("status",))
        self.assertIn("'media' is eligible", err)

    def test_the_answer_changes_nothing(self):
        self.take_creation()
        self.play_session()
        self.checkpoint("final")
        before = self.head()
        self.answer()
        self.assertEqual(before, self.head())
        self.assertEqual(
            "", self.git("diff", "--cached", "--name-only",
                         identity=False).strip())


class TestTheFinalCheckpointMustRecordTheSave(CheckpointFixture):
    """The committer may not certify what the gate rejects.

    The acceptance gate asserts that at least two commits touch the
    userdir -- one after character creation, one after the in-game Save
    and Quit.  This step used to assert nothing of the kind, so it could
    report success on a `final` the gate would then reject, and the
    operator learned about it one stage later from a different tool with
    the commit already taken.
    """

    def test_a_final_carrying_no_save_change_is_refused(self):
        self.take_creation()
        # The record grows, so the lifecycle's row-growth assertion is
        # satisfied -- but the engine never rewrote the save, which is
        # what a session that was never closed looks like.
        self.write_evidence(self.CREATION_ROWS + self.SESSION_ROWS)
        message = self.refuse(EX_LIFECYCLE, ("final",))
        self.assertIn("userdir", message)
        self.assertIn("NOTHING WAS COMMITTED", message)

    def test_the_refusal_happens_before_the_commit(self):
        """Refusing afterwards would leave the bad commit behind."""
        self.take_creation()
        self.write_evidence(self.CREATION_ROWS + self.SESSION_ROWS)
        before = self.head()
        self.refuse(EX_LIFECYCLE, ("final",))
        self.assertEqual(before, self.head())
        self.assertNotIn("Playthrough-Checkpoint: final",
                         self.message())

    def test_a_closed_session_records_the_save_and_says_how_much(self):
        self.take_creation()
        self.play_session()
        _, err = self.checkpoint("final")
        self.assertIn("path(s) under playthrough/userdir", err)
        self.assertTrue(
            any(path.startswith("playthrough/userdir")
                for path in self.touched_by()),
            msg="the final commit recorded nothing under the userdir")

    def test_the_dossier_ordering_is_asserted_by_the_committer_too(self):
        """The gate's other post-commit property, checked here as well."""
        self.forget_dossier()
        self.take_dossier()
        self.take_creation()
        self.play_session()
        _, err = self.checkpoint("final")
        self.assertIn("strict ancestor", err)


class TestALaterFinalMayCarryOnlyTheRender(CheckpointFixture):
    """The film cannot exist until the session is over.

    The save assertion reads the requirement as "a commit after character
    creation AND a commit after the session closed", and refuses a
    `final` carrying no save because such a commit is the second of those
    two in name only.  True of the checkpoint that IS the second one --
    and false of a LATER one.

    The film, the captioned film, the transcripts and the timeline are
    all computed from the finished record, so an operator who closes the
    session, checkpoints the save the engine has just rewritten, and only
    then renders is left holding artifacts the requirement separately
    asks to be committed, with no userdir change to accompany them.
    Refusing that commit made the film uncommittable by the one tool that
    exists to commit it.

    What must NOT become possible is a FIRST `final` that carries no
    save, which is what a session nobody closed looks like -- including
    the version of it where a previous, retired recording's own `final`
    is still sitting in the history.
    """

    OTHER_WORLD = "Apshawa"
    OTHER_CHARACTER = "Ambrose Halloran"
    # base64 of the name above, which is how the engine spells the file.
    OTHER_SAVE = "#QW1icm9zZSBIYWxsb3Jhbg==.sav"

    def render(self):
        """What a post-session render writes, and nothing else.

        No path under the userdir is touched, because the engine has
        already been quit -- which is the whole point of the case.
        """
        self.write(os.path.join(self.dir, "cata-play.mp4"),
                   "the assembled film\n")
        self.write(os.path.join(self.dir, "cata-play-cc.mp4"),
                   "the captioned film\n")
        self.write(os.path.join(self.dir, "timeline.json"), "[]\n")

    def become_the_other_survivor(self):
        """Replace the save with a different survivor's, as retiring a
        superseded recording does: the previous world's files are gone,
        while its commits stay in the history."""
        shutil.rmtree(self.world_dir)
        other_dir = os.path.join(self.dir, "userdir", "save",
                                 self.OTHER_WORLD)
        self.write(os.path.join(other_dir, "master.gsav"),
                   "master state (a different survivor)\n")
        self.write(os.path.join(other_dir, self.OTHER_SAVE),
                   "character state (a different survivor)\n")
        self.write(self.lastworld,
                   json.dumps({"world_name": self.OTHER_WORLD,
                               "character_name": self.OTHER_CHARACTER},
                              indent=2) + "\n")

    def test_the_render_is_committable_once_the_save_is_published(self):
        self.take_creation()
        self.play_session()
        first, _ = self.checkpoint("final")
        self.render()
        second, err = self.checkpoint("final")
        self.assertNotEqual(first["COMMIT"], second["COMMIT"])
        self.assertIn("already published this session's save", err)
        touched = self.touched_by()
        self.assertIn("playthrough/cata-play.mp4", touched)
        self.assertEqual(
            [path for path in touched
             if path.startswith("playthrough/userdir")], [],
            msg="the render commit touched the userdir after all")

    def test_a_first_final_with_only_the_render_is_still_refused(self):
        """The session nobody closed, which is the case to keep."""
        self.take_creation()
        self.write_evidence(self.CREATION_ROWS + self.SESSION_ROWS)
        self.render()
        message = self.refuse(EX_LIFECYCLE, ("final",))
        self.assertIn("and none has", message)
        self.assertIn("NOTHING WAS COMMITTED", message)

    def test_a_retired_recordings_final_does_not_pay_for_this_one(self):
        """Retiring a recording deletes files; it keeps the history.

        So a carve-out phrased as "some reachable final carried a save"
        would be satisfied by somebody else's session.  The retired one
        is not a DESCENDANT of this survivor's creation anchor, and this
        is the case that discriminates.
        """
        self.take_creation()
        self.play_session()
        self.checkpoint("final")
        # The superseded survivor's files go; her checkpoints remain.
        self.become_the_other_survivor()
        self.checkpoint("creation")
        # The new session's record grows -- and the engine is never quit,
        # so nothing under the userdir changes.
        self.write_evidence(
            self.CREATION_ROWS + 2 * self.SESSION_ROWS)
        self.render()
        message = self.refuse(EX_LIFECYCLE, ("final",))
        self.assertIn("and none has", message)
        self.assertIn("NOTHING WAS COMMITTED", message)

    def test_the_carve_out_is_decided_by_strict_ancestry(self):
        """Read from the resolver, whose anchor is now a parameter.

        The comparison used to name CREATION_COMMIT directly.  It reads
        the parameter instead because the read-only `status` subcommand
        asks the same question about a checkpoint it is not taking, and it
        has to pass the anchor it resolved itself -- one implementation
        answers both, so a preflight cannot drift from the refusal it is
        predicting.  What matters here is unchanged: the anchor is
        excluded from its own descendants, because a commit is not its own
        descendant and `--is-ancestor` would otherwise say it is.
        """
        source = self.script_source()
        start = source.index("published_final_for_this_session() {")
        end = source.index("render_completion_note()", start)
        body = source[start:end]
        self.assertIn("merge-base --is-ancestor", body)
        self.assertIn('local anchor="${1:-${CREATION_COMMIT}}"', body)
        self.assertIn('[ "${commit}" != "${anchor}" ]', body)
        self.assertIn("commit_touched", body)
        self.assertIn("final_commits", body)

    def test_the_anchor_itself_never_pays_for_the_render(self):
        """The strictness, driven rather than read.

        A `creation` checkpoint touches the userdir -- it commits the save
        the survivor starts from -- so a carve-out that allowed the anchor
        to satisfy itself would let a `final` carrying no save through on
        the strength of the creation commit alone, which is the very
        session-was-never-closed case it exists to catch.
        """
        self.take_creation()
        self.write_evidence(self.CREATION_ROWS + self.SESSION_ROWS)
        self.render()
        message = self.refuse(EX_LIFECYCLE, ("final",))
        self.assertIn("and none has", message)

    def test_both_assertions_share_one_explanation(self):
        """Two copies of an explanation drift; one cannot."""
        source = self.script_source()
        self.assertEqual(source.count("render_completion_note() {"), 1)
        self.assertEqual(source.count('render_completion_note "'), 2)


class TestTheCommittedVcsRulesGate(CheckpointFixture):
    """The enabling rules have to be IN THE HISTORY, not just on disk.

    `.gitignore`'s terminal negation is what stops git silently skipping
    the engine's own '#<name>.sav' and '*.log' names.  A working tree that
    carries it while HEAD does not is a repository where this history,
    cloned, loses the save data -- and the failure is silent, because
    `git add` skips those paths and exits 0.  So the rules are read out of
    HEAD, not off the disk.
    """

    def test_a_head_without_the_negation_is_refused(self):
        without = SANDBOX_GITIGNORE.replace(NEGATION_LINE + "\n", "")
        self.assertNotIn(NEGATION_LINE, without)
        self.commit_worktree_file(".gitignore", without)
        # The disk still carries it, so only HEAD's copy is at issue.
        self.write(self.gitignore, SANDBOX_GITIGNORE)
        message = self.refuse(EX_PREREQ, ("creation",))
        self.assertIn(NEGATION_LINE, message)

    def test_the_negation_must_be_the_last_matching_rule(self):
        """Order is the whole mechanism: git applies the last match."""
        overridden = SANDBOX_GITIGNORE + "playthrough/userdir/**\n"
        self.commit_worktree_file(".gitignore", overridden)
        message = self.refuse(EX_PREREQ, ("creation",))
        self.assertIn("last", message)

    def test_a_head_missing_one_attribute_row_is_refused(self):
        for row in REQUIRED_ATTRIBUTE_ROWS:
            with self.subTest(row=row):
                self.commit_worktree_file(
                    ".gitattributes",
                    SANDBOX_GITATTRIBUTES.replace(row + "\n", ""))
                message = self.refuse(EX_PREREQ, ("creation",))
                self.assertIn(row, message)
                self.commit_worktree_file(".gitattributes",
                                          SANDBOX_GITATTRIBUTES)

    def test_a_head_that_carries_them_is_reported_as_such(self):
        _, err = self.take_creation()
        self.assertIn(NEGATION_LINE, err)
        self.assertIn("fresh clone", err)

    def test_the_dossier_checkpoint_is_gated_on_them_too(self):
        """The earliest commit of the lifecycle is the one that most
        needs them, because it is the one taken before anybody looks."""
        self.forget_dossier()
        self.commit_worktree_file(
            ".gitignore", SANDBOX_GITIGNORE.replace(
                NEGATION_LINE + "\n", ""))
        self.refuse(EX_PREREQ, ("dossier",))


class TestTheCheckpointLock(CheckpointFixture):
    """Two checkpoints share one index and one HEAD.

    Run concurrently, one stages while the other commits, and the loser
    reports "nothing to commit" about a repository the winner was in the
    middle of changing -- a diagnosis that describes the wrong state.  The
    lock removes the race, and its name carries a digest of THIS checkout
    so a run over a different working tree is not serialised against it.
    """

    def hold_the_lock(self, path):
        """Hold `path` locked for the rest of the test, then let it go.

        The tools are resolved off PATH rather than spelled absolutely:
        this suite already refuses to assume where a tool lives, and a
        hard-coded /usr/bin would make the class silently unrunnable on a
        host that puts flock elsewhere.

        The cleanup KILLS AND THEN REAPS.  A kill alone leaves a zombie
        and Python warns about the still-running child at interpreter
        exit, which is noise that makes a clean run look unclean -- and a
        held lock that outlives its test would fail the next one.
        """
        flock = shutil.which("flock")
        sleep = shutil.which("sleep")
        if not flock or not sleep:
            self.skipTest("flock and sleep are needed to hold a lock")
        holder = subprocess.Popen([flock, path, sleep, "60"])

        def release():
            holder.kill()
            holder.wait(timeout=30)

        self.addCleanup(release)
        # flock has to be scheduled and take the lock before the subject
        # is asked to contend for it, or the test proves nothing.
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if self.lock_is_held(path):
                return holder
            time.sleep(0.1)
        self.fail("the lock holder never acquired %s" % path)

    def lock_is_held(self, path):
        """Whether something else currently holds `path`.

        Asked by trying to take it non-blockingly and reporting the
        failure, which is the same question flock itself answers.
        """
        flock = shutil.which("flock")
        probe = subprocess.run(
            [flock, "--nonblock", path, shutil.which("true")],
            capture_output=True, timeout=60)
        return probe.returncode != 0

    def lock_path(self):
        """The lock file the script will reach for, derived the same way
        it derives it: env.sh's helper, asked directly."""
        script = (
            'set -eu\n'
            '. "%s/env.sh"\n'
            'name="$(playthrough_checkout_lock_name checkpoint)"\n'
            'printf "%%s/%%s.lock\\n" "${PLAYTHROUGH_LOCK_DIR}" "${name}"\n'
        ) % self.tooling
        result = subprocess.run(
            ["/bin/bash", "--noprofile", "--norc", "-c", script],
            cwd=self.checkout, capture_output=True, timeout=120,
            # THE SAME RUNTIME ROOT run_script hands the script.  The
            # lock lives under it, so deriving the path without it names
            # a lock in a different directory -- and a test that holds
            # THAT one leaves the subject free to run, which is a pass
            # reported for a race nobody contended.  Measured: two lock
            # tests went green by never colliding at all.
            env={"PATH": self.bin, "HOME": self.root,
                 "PLAYTHROUGH_RUNTIME_DIR": self.runtime,
                 "PLAYTHROUGH_PYTHON": INTERPRETER})
        out = result.stdout.decode("utf-8", "replace").strip()
        self.assertTrue(
            out, msg="the lock path could not be derived: %s"
                     % result.stderr.decode("utf-8", "replace"))
        return out

    def test_a_busy_checkout_is_refused_rather_than_raced(self):
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        path = self.lock_path()
        self.hold_the_lock(path)
        message = self.refuse(EX_PREREQ, ("creation",),
                              PLAYTHROUGH_CHECKPOINT_LOCK_TIMEOUT="2")
        self.assertIn("another checkpoint is already running", message)
        self.assertIn("THIS RUN COMMITTED NOTHING", message)

    def test_the_refusal_names_the_lock_rather_than_a_host_path(self):
        """Every message goes through env.sh's redaction, which rewrites
        the repository root to '.' -- so naming the path would tell an
        operator nothing.  The digest in the lock name is the scope."""
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        path = self.lock_path()
        name = os.path.basename(path)[:-len(".lock")]
        self.hold_the_lock(path)
        message = self.refuse(EX_PREREQ, ("creation",),
                              PLAYTHROUGH_CHECKPOINT_LOCK_TIMEOUT="2")
        self.assertIn(name, message)
        self.assertRegex(name, r"^checkpoint-[0-9a-f]{8}$")

    def test_the_lock_is_released_and_the_next_run_proceeds(self):
        self.take_creation()
        self.play_session()
        fields, _ = self.checkpoint("final")
        self.assertEqual(fields["COMMITTED"], "yes")

    def test_status_does_not_take_the_lock(self):
        """A read that blocks behind a commit is a reporting tool that
        stops working exactly when an operator needs it."""
        self.take_creation()
        path = self.lock_path()
        self.hold_the_lock(path)
        status, out, _ = self.run_script(
            ("status",), PLAYTHROUGH_CHECKPOINT_LOCK_TIMEOUT="2")
        self.assertEqual(status, EX_OK)
        self.assertEqual(self.payload(out)["CHECKPOINT"], "status")

    def test_a_hostile_timeout_is_refused_before_any_arithmetic(self):
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        self.refuse(EX_USAGE, ("creation",),
                    PLAYTHROUGH_CHECKPOINT_LOCK_TIMEOUT="3; rm -rf /")

    def test_an_out_of_range_timeout_is_refused(self):
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        self.refuse(EX_USAGE, ("creation",),
                    PLAYTHROUGH_CHECKPOINT_LOCK_TIMEOUT="86401")


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

        THE REFUSAL MOVED FORWARD AND GOT BETTER.  This used to rely on
        `git add` erroring when handed an explicit ignored pathspec --
        loud, and the whole reason the captures were never handed to one
        blanket add -- so the diagnosis was git's: it named the file and
        said nothing about WHY a file in this tree may not be excluded.
        A dedicated sweep now asks the question before anything is staged,
        so the answer explains the terminal `!/playthrough/**` negation
        and that a rule placed after it re-excludes whatever it matches.
        It is a scope refusal (EX_SCOPE) rather than a commit one, and
        nothing reaches the index.
        """
        hidden = "playthrough/frames/frame_00003.png"
        self.write(self.gitignore, SANDBOX_GITIGNORE + hidden + "\n")
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        message = self.refuse(EX_SCOPE, ("creation",))
        self.assertIn(hidden, message)
        self.assertIn("IGNORED by git", message)
        self.assertIn(NEGATION_LINE, message)
        self.assertFalse(self.is_tracked(hidden))
        self.assertEqual(
            "", self.git("diff", "--cached", "--name-only",
                         identity=False).strip())

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

    def test_the_subjects_read_as_the_moments_they_record(self):
        """One subject per moment, and `final` no longer claims the lot.

        It used to read "its final save and its artifacts", which was the
        wording of a checkpoint that carried the record, the film and the
        reports together.  The derived artifacts have their own commit
        now, so `final`'s subject is the record alone -- a subject that
        described three things was how a single commit came to be
        expected to cite documents that did not exist yet.
        """
        self.take_creation()
        self.play_session()
        self.checkpoint("final")
        subjects = self.log_subjects()
        self.assertIn("Commit the closed session, its final save and "
                      "its record", subjects[0])
        self.assertIn("Commit the survivor's creation and the save it "
                      "produced", subjects[1])

    def test_the_derived_and_attested_moments_have_their_own_subjects(
            self):
        """The two commits the split added, each about one thing."""
        self.reach_attest()
        self.checkpoint("attest")
        subjects = self.log_subjects()
        self.assertIn("Commit the acceptance report and the final "
                      "three-section report", subjects[0])


class TestTheCheckpointSealsAndPublishesTheEvidence(CheckpointFixture):
    """The half of the evidence anchor that lives in the history.

    A review found every attestation in this tree mutable with the
    evidence it attested to: rewrite a frame, rewrite its digest row, and
    the ledger recomputed from the forged frame agrees with itself.  No
    file in the working tree can settle that, because a file in the
    working tree is exactly what the attacker is editing.

    A COMMIT can.  A commit object's name hashes its own message, so a
    value written into a checkpoint's message is fixed the moment the
    checkpoint is taken -- changing it changes the commit id and every id
    after it, which is a rewrite of published history rather than an edit
    of a file.  So each checkpoint seals the evidence into a hash-chained
    ledger AND publishes that chain's head as a trailer, in the same
    commit that carries the ledger.
    """

    ANCHOR = "playthrough/build/evidence_anchor.jsonl"
    TRAILER = "Playthrough-Evidence-Anchor"

    def anchor_rows(self):
        """The ledger's rows, as JSON, from the working tree."""
        path = os.path.join(self.checkout, self.ANCHOR)
        if not os.path.isfile(path):
            return []
        with open(path, "r", encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def declared(self, revision="HEAD"):
        """The head a commit's trailer publishes, or ''."""
        for line in self.message(revision).split("\n"):
            if line.startswith(self.TRAILER + ": "):
                return line[len(self.TRAILER) + 2:]
        return ""

    def test_the_checkpoint_creates_the_ledger(self):
        self.take_creation()
        self.assertTrue(self.anchor_rows(),
                        msg="the checkpoint sealed nothing")

    def test_the_ledger_is_committed_by_the_checkpoint_that_wrote_it(self):
        """The seal and the claim about it travel together.

        A ledger left uncommitted would be a seal nobody could check
        from the history, and group 7 of the gate would report the tree
        as dirty immediately afterwards.
        """
        self.take_creation()
        self.assertTrue(self.is_tracked(self.ANCHOR))
        self.assertEqual(
            "", self.git("status", "--porcelain", "--", self.ANCHOR,
                         identity=False).strip())

    def test_the_head_is_published_as_a_trailer(self):
        self.take_creation()
        rows = self.anchor_rows()
        self.assertEqual(self.declared(), rows[-1]["chain"])

    def test_the_published_head_is_a_sha256(self):
        self.take_creation()
        self.assertRegex(self.declared(), r"\A[0-9a-f]{64}\Z")

    def test_both_trailers_are_in_one_trailer_block(self):
        """Adjacent lines, so git reads them as trailers.

        A blank line between them would make the second one body text:
        `git log --grep` would still find it and `git interpret-trailers`
        would not, which is the kind of disagreement that surfaces years
        later in whichever tool was not tested.
        """
        self.take_creation()
        lines = [line for line in self.message().split("\n") if line]
        self.assertEqual(lines[-2], "Playthrough-Checkpoint: creation")
        self.assertEqual(lines[-1],
                         "%s: %s" % (self.TRAILER, self.declared()))

    def test_the_record_and_the_films_ledger_are_both_sealed(self):
        """Fifteen rows cover every frame, transitively.

        build/frame_digests.jsonl carries a digest per capture, so
        sealing that one file seals them all: substituting a frame breaks
        its digest row, repairing the digest row breaks this seal, and
        repairing this seal breaks the chain and the head the commit
        published.
        """
        self.take_creation()
        sealed = {row["path"] for row in self.anchor_rows()}
        self.assertIn("manifest.jsonl", sealed)
        self.assertIn("build/frame_digests.jsonl", sealed)

    def test_each_row_seals_by_sha256_and_by_gits_own_blob_name(self):
        self.take_creation()
        for row in self.anchor_rows():
            with self.subTest(path=row["path"]):
                self.assertRegex(row["sha256"], r"\A[0-9a-f]{64}\Z")
                self.assertRegex(row["git_blob"], r"\A[0-9a-f]{40}\Z")

    def test_the_sealed_blob_name_is_the_name_git_gave_it(self):
        """The independent witness, checked against git itself."""
        self.take_creation()
        for row in self.anchor_rows():
            path = "playthrough/" + row["path"]
            if not self.is_tracked(path):
                continue
            with self.subTest(path=path):
                self.assertEqual(
                    self.git("rev-parse", "HEAD:" + path,
                             identity=False).strip(),
                    row["git_blob"])

    def test_the_row_records_the_checkpoint_that_sealed_it(self):
        self.take_creation()
        self.assertEqual(
            {row["sealed_by"] for row in self.anchor_rows()},
            {"creation"})

    def test_a_later_checkpoint_appends_and_republishes(self):
        """Append-only, and the new head is published in its turn."""
        self.take_creation()
        first = self.declared()
        before = len(self.anchor_rows())
        self.play_session()
        self.checkpoint("final")
        rows = self.anchor_rows()
        self.assertGreater(len(rows), before)
        self.assertEqual([row["seq"] for row in rows],
                         list(range(1, len(rows) + 1)))
        self.assertNotEqual(self.declared(), first)
        self.assertEqual(self.declared(), rows[-1]["chain"])
        # The earlier head is still in the history, on its own commit.
        self.assertEqual(self.declared("HEAD~1"), first)

    def test_the_earlier_rows_are_never_rewritten(self):
        self.take_creation()
        before = self.anchor_rows()
        self.play_session()
        self.checkpoint("final")
        self.assertEqual(self.anchor_rows()[:len(before)], before)

    def test_the_integration_milestone_seals_nothing(self):
        """It commits the two rule files and touches no evidence.

        A milestone that sealed an empty tree would put a row in the
        chain vouching for nothing, and would publish a head that no
        artifact stands behind.
        """
        self.checkpoint("integration")
        self.assertEqual(self.anchor_rows(), [])
        self.assertEqual(self.declared(), "")

    def test_a_broken_chain_stops_the_next_checkpoint(self):
        """Fail-closed: a checkpoint is not taken over an unsound seal.

        Appending onto a chain that is already broken would bury the
        break under rows that all verify against one another.
        """
        self.take_creation()
        head_before = self.git("rev-parse", "HEAD",
                               identity=False).strip()
        path = os.path.join(self.checkout, self.ANCHOR)
        rows = self.anchor_rows()
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            for row in rows[1:]:
                handle.write(json.dumps(row, separators=(",", ":")) + "\n")
        self.play_session()
        message = self.refuse(EX_COMMIT, ("final",))
        self.assertIn("not a sound chain", message)
        self.assertEqual(
            self.git("rev-parse", "HEAD", identity=False).strip(),
            head_before,
            msg="a checkpoint was taken despite an unsound seal")


class TestTheStagedTreeIsWhatItAppearsToBe(CheckpointFixture):
    """WHAT a path is, as opposed to where it is.

    The engine's own subtree is classified by POSITION, and it has to be:
    the engine writes `#<b64>.sav`, `.seen.0.-1`, `.mm1` directories and
    `<name>-<serial>.json.-4651329699267.fb` caches, so a per-filename
    allowlist over somebody else's output would refuse a correct
    checkpoint the first time a new engine version wrote a new shape.

    A review found what position alone cannot see. The classification
    sweep enumerates with `find -type f`, and `-type f` is TRUE of a hard
    link to a file anywhere else on the same filesystem -- so a second
    link to something outside this tree, dropped into a directory the
    engine owns, is classified as engine state and committed whole. The
    same sweep cannot see a symlink at all, so a symlink is an
    unclassified path the classification refusal never gets to refuse.

    So these properties are asked of every entry, by what it IS, which is
    a question the engine's freedom to name its own files does not touch.
    """

    def engine_path(self, name):
        """A path inside a directory the engine legitimately owns."""
        return os.path.join(self.dir, "userdir", "cache", name)

    def prepared(self):
        """The tree a creation checkpoint would be taken over."""
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)

    def test_an_ordinary_tree_passes_and_says_so(self):
        """The positive control: the check must not be unconditional."""
        self.prepared()
        fields, output = self.checkpoint("creation")
        self.assertEqual(fields["COMMITTED"], "yes")
        self.assertIn("single-linked regular file", output)

    def test_a_hard_link_into_the_engine_tree_is_refused(self):
        """CWE-59, and the reason `-type f` is not enough.

        The link is a perfectly ordinary regular file by every test the
        classification makes, it sits in a directory the engine owns, and
        its content is somebody else's.
        """
        self.prepared()
        outsider = os.path.join(self.checkout, "outside-the-tree.txt")
        self.write(outsider, "content that belongs to another file\n")
        planted = self.engine_path("tile-cache.json")
        os.makedirs(os.path.dirname(planted), exist_ok=True)
        os.link(outsider, planted)
        message = self.refuse(EX_SCOPE, ("creation",))
        self.assertIn("userdir/cache/tile-cache.json", message)
        self.assertIn("hard links", message)
        self.assertIn("reachable outside this tree", message)

    def test_a_symlink_in_the_engine_tree_is_refused(self):
        """The path the classification sweep cannot even see."""
        self.prepared()
        planted = self.engine_path("tiles.png")
        os.makedirs(os.path.dirname(planted), exist_ok=True)
        os.symlink("/etc/hostname", planted)
        message = self.refuse(EX_SCOPE, ("creation",))
        self.assertIn("userdir/cache/tiles.png", message)
        self.assertIn("symbolic link", message)

    def test_a_dangling_symlink_is_refused_too(self):
        """Nothing to read is not a reason to let it through."""
        self.prepared()
        planted = self.engine_path("gone.json")
        os.makedirs(os.path.dirname(planted), exist_ok=True)
        os.symlink(os.path.join(self.root, "does-not-exist"), planted)
        message = self.refuse(EX_SCOPE, ("creation",))
        self.assertIn("symbolic link", message)

    def test_a_named_pipe_is_refused(self):
        """A file that is not a file, which `git add` would hang on."""
        self.prepared()
        planted = self.engine_path("pipe")
        os.makedirs(os.path.dirname(planted), exist_ok=True)
        os.mkfifo(planted)
        self.addCleanup(_unlink_if_present, planted)
        message = self.refuse(EX_SCOPE, ("creation",))
        self.assertIn("not a regular file or a directory", message)

    def test_a_path_owned_by_another_account_is_refused(self):
        """Somebody else put this here.

        Skipped where this account cannot change ownership, because then
        the state under test cannot be constructed honestly.
        """
        self.prepared()
        planted = self.engine_path("notes.json")
        self.write(planted, "{}\n")
        try:
            os.chown(planted, 12345, 12345)
        except (OSError, OverflowError) as err:
            self.skipTest("cannot change ownership here: %s" % err)
        message = self.refuse(EX_SCOPE, ("creation",))
        self.assertIn("userdir/cache/notes.json", message)
        self.assertIn("owned by uid 12345", message)
        self.assertIn("placed here by somebody else", message)

    def test_another_filesystem_inside_the_tree_is_refused(self):
        """A grafted mount, which is a whole tree of somebody's content.

        Skipped where mounting is not available, for the same reason as
        the ownership case: an unconstructable state is not a passing one.
        """
        self.prepared()
        planted = self.engine_path("mounted")
        os.makedirs(planted, exist_ok=True)
        mount = subprocess.run(
            ["mount", "-t", "tmpfs", "-o", "size=1m", "tmpfs", planted],
            capture_output=True, timeout=60)
        if mount.returncode != 0:
            self.skipTest("cannot mount here: %s"
                          % mount.stderr.decode("utf-8", "replace"))

        # UNMOUNTED BEFORE THE TREE IS REMOVED, and lazily if the plain
        # form is busy: leaving a mount behind would outlive this suite.
        def unmount():
            if subprocess.run(["umount", planted],
                              capture_output=True).returncode != 0:
                subprocess.run(["umount", "-l", planted],
                               capture_output=True)
        self.addCleanup(unmount)
        self.write(os.path.join(planted, "planted.json"), "{}\n")
        message = self.refuse(EX_SCOPE, ("creation",))
        self.assertIn("another filesystem is mounted inside this tree",
                      message)

    def test_the_dossier_checkpoint_asks_the_same_questions(self):
        """It stages one path and still seals the whole tree."""
        self.forget_dossier()
        planted = self.engine_path("tile-cache.json")
        outsider = os.path.join(self.checkout, "outside-the-tree.txt")
        self.write(outsider, "somebody else's content\n")
        os.makedirs(os.path.dirname(planted), exist_ok=True)
        os.link(outsider, planted)
        message = self.refuse(EX_SCOPE, ("dossier",))
        self.assertIn("hard links", message)


class TestSecretMaterialIsRefusedBeforeStaging(CheckpointFixture):
    """The content question, which no structural check can answer.

    A review put the vector plainly: "an innocuously named inserted
    credential can be committed". Every other gate in this script asks
    where a path is, what it is called and what shape it has, and a file
    called `userdir/cache/tile-cache.json` holding an access token
    satisfies all three.

    The scan that answers it had to be measured in BOTH directions before
    it could be trusted, and the first measurement is why it looks the
    way it does: run over the delivered tree, a plain-vocabulary version
    reported twelve findings and every one was a false positive on this
    feature's own documentation of the hazard. So the rules describe
    secret VALUES, and the tests below hold both halves -- what must be
    caught, and what must not be.
    """

    # One planted file per rule, each a realistic shape and none of them
    # a credential to anything that exists.
    #
    # EVERY VALUE IS ASSEMBLED FROM TWO PIECES, and that is load-bearing
    # rather than a style: written as whole literals, this file CARRIES
    # the eight shapes it exists to prove are caught, and the committer's
    # own scan then reports this suite as holding ten credentials.
    # Measured exactly that way -- ten findings, all of them here -- which
    # is the same self-reference the scanner's own patterns had to be
    # written around. Splitting each value puts a quote and a `+` where
    # the expression needs the next character of the secret, so the file
    # no longer matches while the runtime string still does. The tests
    # below prove the assembled values ARE caught, which is what keeps
    # this from quietly disarming the fixtures.
    CAUGHT = (
        ("token.json",
         '{"remote":"https://x-access-token:' +
         "ghs_" + 'AbCdEfGhIjKlMnOpQrStUvWxYz012345' +
         '@github.com/o/r.git"}\n'),
        ("aws.txt", "AKIA" + "IOSFODNN7EXAMPLE\n"),
        ("google.txt", "AIza" + "SyA1234567890abcdefghijklmnopqrstuvw\n"),
        ("slack.txt", "xoxb" + "-1234567890-abcdefghijkl\n"),
        ("key.pem",
         "-----BEGIN " + "OPENSSH PRIVATE KEY-----\nb3BlbnNzaA\n"),
        ("cookie.txt",
         "MIT-MAGIC-COOKIE-1  " +
         "0123456789abcdef" + "0123456789abcdef\n"),
        ("bearer.txt",
         "Authorization: Bearer " +
         "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9\n"),
        ("basic.txt",
         "Authorization: Basic " + "QWxhZGRpbjpvcGVuIHNlc2FtZQ==\n"),
    )

    # And what must NOT be reported, each taken from something that really
    # appears in this tree.
    PASSED_OVER = (
        ("protocol.txt", "MIT-MAGIC-COOKIE-1 is the protocol name\n"),
        ("digest.txt", "MD5=4c38e03830e7d4a278f237276b9dae46\n"),
        ("redacted.txt",
         "https://x-access-token:<secret>@github.com/o/r.git\n"),
        ("expanded.txt", "https://user:${TOKEN}@example.invalid/r.git\n"),
        ("starred.txt", "https://user:****@example.invalid/r.git\n"),
        ("prose.txt",
         "The remote carries an x-access-token and the config is 0600.\n"),
    )

    def plant(self, name, text):
        """Write one file into a directory the engine legitimately owns."""
        return self.write(
            os.path.join(self.dir, "userdir", "cache", name), text)

    def prepared(self):
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)

    def test_a_credential_in_an_innocuously_named_file_is_refused(self):
        """The review's stated vector, end to end."""
        self.prepared()
        self.plant("tile-cache.json", self.CAUGHT[0][1])
        message = self.refuse(EX_SCOPE, ("creation",))
        self.assertIn("carry secret material", message)
        self.assertIn("userdir/cache/tile-cache.json", message)
        self.assertIn("url-credential", message)

    def test_the_value_is_never_printed(self):
        """A refusal that quoted the secret would publish it itself.

        Into the log, the terminal and whatever CI transcript is keeping
        them -- which is the outcome this whole gate exists to prevent, so
        the diagnostic names the rule and the path and nothing else.
        """
        self.prepared()
        self.plant("tile-cache.json", self.CAUGHT[0][1])
        message = self.refuse(EX_SCOPE, ("creation",))
        self.assertNotIn("ghs_" + "AbCdEfGhIjKlMnOpQrStUvWxYz012345",
                         message)
        self.assertNotIn("x-access-token:" + "ghs_", message)

    def test_every_rule_catches_its_own_shape(self):
        for name, text in self.CAUGHT:
            with self.subTest(name=name):
                self.setUp()
                self.prepared()
                self.plant(name, text)
                message = self.refuse(EX_SCOPE, ("creation",))
                self.assertIn("carry secret material", message)
                self.assertIn("userdir/cache/" + name, message)

    def test_what_must_not_be_reported_is_not(self):
        """All of them at once: a false positive here refuses every run."""
        self.prepared()
        for name, text in self.PASSED_OVER:
            self.plant(name, text)
        fields, output = self.checkpoint("creation")
        self.assertEqual(fields["COMMITTED"], "yes")
        self.assertIn("found nothing unaccounted for", output)

    def test_a_binary_capture_is_skipped_rather_than_decoded(self):
        """The scan is affordable over ten thousand captures because of it.

        A PNG's first bytes carry a NUL, so the frames, both films and the
        engine's binary save files never reach the expressions at all.
        """
        self.prepared()
        self.plant("blob.dat", "AKIA" + "IOSFODNN7EXAMPLE\n")
        # The same bytes with a NUL in front are not text and are skipped,
        # which is the behaviour being pinned -- not an exemption for
        # anything whose name ends in .dat.
        path = os.path.join(self.dir, "userdir", "cache", "blob.dat")
        with open(path, "wb") as handle:
            handle.write(b"\x89PNG\r\n\x1a\n\x00" +
                         b"AKIA" + b"IOSFODNN7EXAMPLE\n")
        fields, output = self.checkpoint("creation")
        self.assertEqual(fields["COMMITTED"], "yes")
        self.assertIn("found nothing unaccounted for", output)

    def test_the_baseline_pins_the_path_as_well_as_the_value(self):
        """The reviewed fixture is excused where it is, and nowhere else.

        The one baselined finding is a test fixture in
        test_commit_artifacts.py. The SAME value planted in the engine's
        tree is a different finding and is refused, because an entry pins
        the path, the rule and the digest together.
        """
        self.prepared()
        self.plant("copy.json",
                   "https://x-access-token:s3cr3t@github.com/o/r.git\n")
        message = self.refuse(EX_SCOPE, ("creation",))
        self.assertIn("userdir/cache/copy.json", message)
        self.assertIn("url-credential", message)

    def test_the_scanner_does_not_report_itself(self):
        """It quotes the shapes it looks for, and must not match them.

        Measured before it shipped: written as plain literals, the
        private-key and PuTTY rules matched their own source and the scan
        reported the scanner as carrying a key. The positive control for
        that a checkpoint succeeds over a tree which CONTAINS the scanner,
        and that is asserted directly here rather than left implicit in
        every other test.
        """
        self.prepared()
        # The sandbox really does carry the script, so the scan really
        # does read the file that quotes every pattern it applies.
        scanner = os.path.join(self.tooling, SCRIPT_NAME)
        self.assertTrue(os.path.isfile(scanner))
        with open(scanner, "r", encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("private-key", source)
        self.assertIn("putty-key", source)
        fields, output = self.checkpoint("creation")
        self.assertEqual(fields["COMMITTED"], "yes")
        self.assertIn("found nothing unaccounted for", output)

    def test_the_baseline_is_a_reviewed_list_not_an_exemption(self):
        """Every entry names a path, a rule and a digest -- no wildcards.

        A baseline that excused a FILE, or a rule everywhere, would be an
        exclusion wearing a baseline's name. The delivered list has one
        entry and it is fully qualified; the digest is there so the list
        itself carries no credential-shaped string.
        """
        with open(os.path.join(TOOLING, SCRIPT_NAME), "r",
                  encoding="utf-8") as handle:
            source = handle.read()
        start = source.index("readonly -a SECRET_BASELINE=(")
        block = source[start:source.index(")\n", start)]
        entries = [line.strip().strip('"').rstrip("\\")
                   for line in block.split("\n")[1:] if line.strip()]
        joined = "".join(entries)
        fields = joined.split("|")
        self.assertEqual(len(fields), 3, msg=joined)
        self.assertTrue(fields[0].startswith("playthrough/"))
        self.assertNotIn("*", fields[0])
        self.assertRegex(fields[2], r"\A[0-9a-f]{64}\Z")


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

    def test_an_empty_record_is_counted_as_zero_and_not_as_nothing(self):
        """The two counters agree about an absent record.

        ROWS was left EMPTY when no manifest existed while FRAMES beside
        it reported 0, so the two fields disagreed about the same empty
        record and a reader comparing them -- which is exactly what the
        readme documents doing -- had to know that one absence is spelled
        `0` and the other is spelled nothing.  This is the state a
        checkout is in between a retirement and the re-record that
        replaces it, so it is a state the tool supports rather than an
        edge case.
        """
        status, out, _ = self.run_script(("status",))
        self.assertEqual(status, EX_OK)
        fields = self.payload(out)
        self.assertEqual(fields["ROWS"], "0")
        self.assertEqual(fields["FRAMES"], "0")
        self.assertEqual(fields["FRAMES"], fields["ROWS"])

    def test_status_lists_what_a_checkpoint_would_stage(self):
        self.write_save()
        self.write_evidence(self.CREATION_ROWS)
        _, _, err = self.run_script(("status",))
        self.assertIn("would stage", err)
        self.assertIn("playthrough/manifest.jsonl", err)

    def test_the_preview_is_bounded_and_states_the_exact_total(self):
        """A report an operator can read at any session length.

        `status` used to capture the whole `git add --dry-run` output and
        print all of it, which on a played session is one line per
        capture -- in memory and on the terminal.  The total is exact and
        the sample is bounded, so the answer stays an answer.
        """
        with open(os.path.join(TOOLING, SCRIPT_NAME),
                  encoding="utf-8") as handle:
            limit = int(re.search(r"PREVIEW_LIMIT=(\d+)",
                                  handle.read()).group(1))
        count = limit + 25
        self.write_save()
        self.write_evidence(count)
        status, _, err = self.run_script(("status",))
        self.assertEqual(status, EX_OK)
        match = re.search(r"would stage (\d+) path\(s\); the first "
                          r"(\d+) are:", err)
        self.assertIsNotNone(
            match, msg="the preview does not state its bound:\n%s" % err)
        total, shown = int(match.group(1)), int(match.group(2))
        self.assertGreater(total, count)
        self.assertEqual(shown, limit)
        self.assertEqual(
            len([line for line in err.splitlines()
                 if line.startswith("add '")]), limit,
            msg="the preview printed more than its bound:\n%s" % err)


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
            env={"PATH": self.bin, "GIT_CONFIG_GLOBAL": self.global_config,
                 "GIT_CONFIG_NOSYSTEM": "1"},
            timeout=60)
        return result.returncode


class TestTheLastThreeCheckpointsAreOrdered(CheckpointFixture):
    """`final` -> `media` -> `attest`, and why they are three.

    One checkpoint used to carry the record, the film and the reports, and
    it demanded playthrough/REPORT.md before it would run.  The report
    cites the commits carrying the film and the acceptance evidence, so
    that ordering was unsatisfiable: the document had to cite commits that
    did not exist yet, and the delivered one duly cited an earlier
    session's instead.

    Split, each commit is about one thing and cites only what already
    precedes it.  These tests are the fence around the ordering.
    """

    def test_final_no_longer_demands_the_report(self):
        """The unsatisfiable requirement, positively asserted as gone.

        This is the fix stated as behaviour rather than as an absence: a
        session that has closed can be committed with no report in the
        tree at all, because at that moment there is nothing for a report
        to be about.
        """
        self.take_creation()
        self.play_session()
        os.unlink(self.report)
        fields, _ = self.checkpoint("final")
        self.assertEqual(fields["COMMITTED"], "yes")

    def test_media_without_a_published_final_is_refused(self):
        """A film of a record that was never committed."""
        self.take_creation()
        self.play_session()
        message = self.refuse(EX_LIFECYCLE, ("media",))
        self.assertIn("'final'", message)
        self.assertIn("Nothing was committed", message)

    def test_attest_without_a_published_final_is_refused(self):
        """And the measurement has to be there first to reach it.

        The gates run before the lifecycle question, so a missing
        acceptance report is answered first -- with EX_EVIDENCE, which is
        the right order and a different refusal.  The report is written
        here so the one under test is the one that fires.
        """
        self.take_creation()
        self.play_session()
        self.write_acceptance_report()
        message = self.refuse(EX_LIFECYCLE, ("attest",))
        self.assertIn("'final'", message)
        self.assertIn("Nothing was committed", message)

    def test_the_three_run_in_order_and_each_records_its_trailer(self):
        """Read out of the messages themselves, newest commit first.

        The trailer is the lifecycle's ENTIRE persistent state -- there is
        no side file to fall out of step with the history -- so the order
        the commits were taken in is exactly what the log says it is.
        """
        self.reach_attest()
        self.checkpoint("attest")
        log = self.git("log", "--format=%B", identity=False)
        recorded = [line.split(": ", 1)[1].strip()
                    for line in log.split("\n")
                    if line.startswith("Playthrough-Checkpoint: ")]
        self.assertEqual(recorded[0], "attest",
                         msg="the newest commit is not the attestation")
        for name in ("media", "final", "creation"):
            self.assertIn(name, recorded,
                          msg="no commit carries the '%s' trailer" % name)
        # And the order, newest first, is the documented one.
        self.assertLess(recorded.index("attest"),
                        recorded.index("media"),
                        msg="attest must be NEWER than media")
        self.assertLess(recorded.index("media"),
                        recorded.index("final"),
                        msg="media must be NEWER than final")

    def test_a_death_ended_session_can_still_commit_its_own_film(self):
        """ALL THREE ARE POST-SESSION, not just the first of them.

        A session that ends in death leaves no live character save: the
        engine moves the survivor into the graveyard and writes the
        memorial pair, which `final` accepts as the death shape.  The film
        and the report are produced AFTERWARDS, from that same finished
        record -- so if `media` and `attest` were held to the live-save
        shape the way a pre-session checkpoint is, a survivor who died
        could never commit the film of their own death.

        Driven rather than read off the predicate, because that predicate
        is a list of three names and a list can lose one silently:
        narrowed to `final` alone, every source assertion about it still
        held and only this run noticed.
        """
        self.take_creation()
        self.play_session()
        self.write_death_persistence()
        final, _ = self.checkpoint("final")
        self.assertEqual(final["COMMITTED"], "yes")

        self.write_media()
        media, _ = self.checkpoint("media")
        self.assertEqual(media["COMMITTED"], "yes")

        self.write_acceptance_report()
        attest, _ = self.checkpoint("attest")
        self.assertEqual(attest["COMMITTED"], "yes")


class TestTheAcceptanceReportIsPublishedByAttestAlone(CheckpointFixture):
    """The measurement, and the three questions asked before it is kept.

    verify_artifacts.sh used to write playthrough/acceptance-report.txt
    itself -- on a passing run, from inside the tree it was measuring,
    after the very checks that assert that tree is clean and fully
    committed -- and DELETE it on a failing one.  A review measured the
    consequence: a full-phase run taken after the final checkpoint left
    the tree dirty in the one file it had just certified as committed.  A
    measurement that publishes itself invalidates its own last finding.

    So the gate writes to a scratch path outside the checkout and this
    checkpoint publishes.  That puts three questions between the two which
    a self-publishing gate could not ask itself: is there a report, did it
    PASS, and is it about THIS tree.
    """

    def test_no_report_at_the_scratch_path_is_refused(self):
        self.reach_media()
        self.checkpoint("media")
        message = self.refuse(EX_EVIDENCE, ("attest",))
        self.assertIn("no acceptance report to publish", message)
        self.assertIn("--report-to", message)

    def test_a_failing_measurement_is_not_committed(self):
        """A red verdict archived as evidence would read as a green one."""
        self.reach_attest(verdict="fail")
        message = self.refuse(EX_EVIDENCE, ("attest",))
        self.assertIn("VERIFY=fail", message)
        self.assertIn("failing measurement", message)

    def test_a_named_divergence_is_published_rather_than_refused(self):
        """The honest verdict has to be the publishable one.

        The gate has a third verdict, `pass-with-divergence`, for a run
        where nothing FAILED but some property the plan asks for is
        delivered differently and the report says so in full.  It exists
        because a review found the opposite handling of exactly one such
        property -- a known, permanent, environment-imposed divergence
        recorded as a PASS -- and named the resulting report as the
        defect.

        If this checkpoint refused that verdict, the only report it could
        ever commit would be one that called the divergence a pass: the
        honest measurement would be unpublishable and the dishonest one
        mandatory.  So the refusal is on `fail` alone, and the log line
        says which verdict it published and how many divergences it
        carried, rather than passing it through silently.
        """
        self.reach_attest(verdict="pass-with-divergence")
        fields, err = self.checkpoint("attest")
        self.assertEqual(fields["COMMITTED"], "yes")
        self.assertIn("published the acceptance report", err)
        self.assertIn("pass-with-divergence", err)
        self.assertIn("divergence(s) from the plan", err)
        self.assertTrue(
            self.is_tracked("playthrough/acceptance-report.txt"))

    def test_a_verdict_this_checkpoint_does_not_know_is_refused(self):
        """The allowance is a list, not "anything that starts with pass".

        A prefix test would admit any future token somebody invented,
        including one meaning the opposite of what it looked like.  The
        two publishable verdicts are enumerated, an unknown one is
        refused, and the refusal names the set so the operator does not
        have to read this file to find out what it would have accepted.
        """
        self.reach_attest(verdict="pass-with-caveat")
        message = self.refuse(EX_EVIDENCE, ("attest",))
        self.assertIn("pass-with-caveat", message)
        self.assertIn("pass pass-with-divergence", message)
        self.assertFalse(
            self.is_tracked("playthrough/acceptance-report.txt"))

    def test_a_report_from_the_artifacts_only_phase_is_refused(self):
        """It measured no history, and history is what this attests to."""
        self.reach_attest(phase="pre-commit")
        message = self.refuse(EX_EVIDENCE, ("attest",))
        self.assertIn("pre-commit", message)
        self.assertIn("post-commit", message)

    def test_a_report_about_another_commit_is_refused(self):
        """The stale citation, made impossible to commit.

        A report generated, left while further commits landed, and only
        then committed is stale in exactly the way a review found: a
        committed report naming a HEAD and a check total that had both
        moved on, every number in it correctly derived and the citation
        false anyway.
        """
        self.reach_attest(measured="HEAD 0123456789")
        message = self.refuse(EX_LIFECYCLE, ("attest",))
        self.assertIn("0123456789", message)
        self.assertIn(self.short_head(), message)

    def test_a_measurement_over_a_dirty_tree_is_refused(self):
        """Provisional by construction, and it says so in that line.

        The gate appends "plus N uncommitted path(s)" when the tree it
        measured was not the commit it names, so a report taken mid-edit
        cannot be mistaken for evidence about a commit -- and cannot be
        committed as one.
        """
        self.reach_attest()
        self.write_acceptance_report(
            measured="HEAD %s plus 3 uncommitted path(s) under "
                     "playthrough" % self.short_head())
        message = self.refuse(EX_LIFECYCLE, ("attest",))
        self.assertIn("uncommitted", message)

    def test_a_passing_measurement_about_this_head_is_published(self):
        self.reach_attest()
        fields, err = self.checkpoint("attest")
        self.assertEqual(fields["COMMITTED"], "yes")
        self.assertIn("published the acceptance report", err)
        self.assertTrue(
            self.is_tracked("playthrough/acceptance-report.txt"))
        self.assertIn("playthrough/acceptance-report.txt",
                      self.touched_by())

    def test_what_is_published_is_byte_identical_to_what_was_measured(
            self):
        """Publication is a copy, not a rewrite of the verdict."""
        self.reach_attest()
        self.checkpoint("attest")
        with open(self.acceptance_scratch, "rb") as handle:
            measured = handle.read()
        published = os.path.join(self.checkout, "playthrough",
                                 "acceptance-report.txt")
        with open(published, "rb") as handle:
            self.assertEqual(handle.read(), measured)

    def test_the_earlier_checkpoints_never_create_it(self):
        """Only `attest` publishes, so nothing else may leave it behind."""
        published = os.path.join(self.checkout, "playthrough",
                                 "acceptance-report.txt")
        self.reach_media()
        self.assertFalse(os.path.exists(published))
        self.checkpoint("media")
        self.assertFalse(os.path.exists(published))


class TestTheAttestationReportGate(CheckpointFixture):
    """The deliverable's own document, and why its absence was silent.

    playthrough/REPORT.md is named in env.sh and STAGED with the
    narrative class -- and staging a path that is not there is
    deliberately not fatal, because several narrative artifacts are
    genuinely optional.  So a checkpoint could be taken, and pass every
    other gate in this file, with no report in the tree at all: the
    omission was one line in a log, and the published history carried a
    film with nothing explaining it.

    IT IS DEMANDED AT `attest` AND NOT AT `final`, and that move is a
    finding of its own.  The report cites the commits carrying the film,
    the transcripts and the acceptance evidence, so requiring it at
    `final` -- taken the instant the session closes, before a single
    derived artifact exists -- required the document to cite commits that
    had not been made.  The delivered report duly cited an EARLIER
    session's, because those were the only ones available when the rule
    forced it to be written.  `attest` runs after `final` and `media`, so
    everything it cites already precedes it.

    The requirement fixes the report's shape -- exactly three sections,
    A) Screen Recording and Animation, B) Character Creation, C) Playing
    the Game, in that order -- so each way of getting it wrong is its own
    refusal.  What is NOT checked is the prose: whether a section says
    enough is a reader's judgement and cannot be a shell script's.
    """

    def reach_gate(self):
        """Get the fixture to the point where the report is demanded."""
        self.reach_attest()

    def test_an_attest_checkpoint_with_no_report_is_refused(self):
        self.reach_gate()
        os.unlink(self.report)
        message = self.refuse(EX_EVIDENCE, ("attest",))
        self.assertIn("playthrough/REPORT.md", message)
        self.assertIn("Screen Recording and Animation", message)
        self.assertIn("Nothing was committed", message)

    def test_an_empty_report_is_refused(self):
        """A placeholder is the same absence with a file in the way."""
        self.reach_gate()
        self.write(self.report, "")
        message = self.refuse(EX_EVIDENCE, ("attest",))
        self.assertIn("is empty", message)

    def test_a_report_missing_a_section_is_refused(self):
        for dropped in REPORT_SECTIONS:
            with self.subTest(section=dropped):
                self.setUp()
                self.reach_gate()
                self.write(self.report, report_text(
                    tuple(section for section in REPORT_SECTIONS
                          if section != dropped)))
                message = self.refuse(EX_EVIDENCE, ("attest",))
                self.assertIn("2 top-level section(s)", message)
                self.assertIn(dropped, message)

    def test_a_renamed_section_is_refused_and_both_names_are_named(self):
        self.reach_gate()
        self.write(self.report, report_text(
            ("## A) Screen Recording and Animation",
             "## B) The Survivor",
             "## C) Playing the Game")))
        message = self.refuse(EX_EVIDENCE, ("attest",))
        self.assertIn("## B) The Survivor", message)
        self.assertIn("## B) Character Creation", message)

    def test_a_fourth_section_is_refused(self):
        """A report that grew a section is not the document asked for."""
        self.reach_gate()
        self.write(self.report, report_text(
            REPORT_SECTIONS + ("## D) Further Thoughts",)))
        message = self.refuse(EX_EVIDENCE, ("attest",))
        self.assertIn("4 top-level section(s)", message)
        self.assertIn("## D) Further Thoughts", message)

    def test_sections_in_the_wrong_order_are_refused(self):
        self.reach_gate()
        self.write(self.report, report_text(
            ("## B) Character Creation",
             "## A) Screen Recording and Animation",
             "## C) Playing the Game")))
        message = self.refuse(EX_EVIDENCE, ("attest",))
        self.assertIn("where section 1 must be", message)

    def test_subsections_are_not_counted_as_sections(self):
        """The real report has many; a gate that counted them would
        refuse every correct report."""
        self.reach_gate()
        with open(self.report, encoding="utf-8") as handle:
            self.assertIn("### ", handle.read())
        fields, err = self.checkpoint("attest")
        self.assertEqual(fields["COMMITTED"], "yes")
        self.assertIn("all 3 of its sections, in order", err)

    def test_the_attest_checkpoint_publishes_the_report(self):
        """Staged by the checkpoint, and tracked at HEAD afterwards."""
        self.reach_gate()
        self.write(self.report, report_text() + "\nOne more line.\n")
        self.checkpoint("attest")
        self.assertIn("playthrough/REPORT.md", self.touched_by())
        self.assertTrue(self.is_tracked("playthrough/REPORT.md"))

    def test_the_earlier_checkpoints_do_not_require_it(self):
        """They run before the recording exists, so it cannot yet.

        `integration` and `dossier` precede the session and `creation`
        precedes the first rendered frame -- a report about a finished
        recording written at any of them would be a report about nothing.
        """
        os.unlink(self.report)
        # `integration` needs something to commit, and the negation has
        # to stay the last effective rule, so the note goes above it.
        self.write(self.gitignore, SANDBOX_GITIGNORE.replace(
            NEGATION_LINE, "# an operator's note\n" + NEGATION_LINE))
        self.checkpoint("integration")
        self.forget_dossier()
        self.take_dossier()
        fields, _ = self.take_creation()
        self.assertEqual(fields["COMMITTED"], "yes")

    def test_the_status_subcommand_does_not_require_it_either(self):
        """It is read-only; refusing there would help nobody."""
        os.unlink(self.report)
        status, _, err = self.run_script(("status",))
        self.assertEqual(status, EX_OK, msg=err)


class TestTheAttributesGitWouldActuallyApply(CheckpointFixture):
    """The rows are present -- would git apply them?

    git takes the LAST matching pattern, in .gitattributes exactly as in
    .gitignore.  A rule added after this feature's rows silently replaces
    them while the row-by-row check still passes, and the consequence is
    not cosmetic: with the film left to `text`, `git add` runs
    end-of-line normalisation over an h264 stream and commits a container
    nothing can play, and every count in this script still tallies.

    So these tests ask git itself, with `git check-attr`, about one
    representative path per row -- which is also the only form of the
    question that survives a rule written as a directory pattern or a
    literal filename rather than as a suffix.
    """

    def effective(self, path, attribute, source=None):
        """What git would apply to `path`, per `git check-attr`."""
        arguments = ["check-attr"]
        if source:
            arguments.append("--source=%s" % source)
        arguments.extend([attribute, "--", path])
        line = self.git(*arguments, identity=False).strip()
        self.assertTrue(line, msg="git said nothing about %s" % path)
        return line.rsplit(": ", 1)[1]

    def test_the_committed_rows_produce_the_intended_attributes(self):
        """The positive control, on the working tree and on HEAD.

        Asserted as effective ATTRIBUTES rather than as rows, because a
        row is only evidence that somebody wrote one down.
        """
        for path, attribute, wanted in ATTRIBUTE_WITNESSES:
            with self.subTest(path=path):
                self.assertEqual(self.effective(path, attribute), wanted)
                self.assertEqual(
                    self.effective(path, attribute, source="HEAD"),
                    wanted)

    def test_binary_artifacts_get_the_whole_binary_macro(self):
        """`binary` is -text -diff -merge, and the diff half matters too:
        a textual diff of a three-megabyte film is unreadable noise."""
        for path in ("playthrough/cata-play.mp4",
                     "playthrough/userdir/save/World/maps.zzip"):
            with self.subTest(path=path):
                self.assertEqual(self.effective(path, "diff"), "unset")

    def test_a_later_override_changes_what_git_applies(self):
        """The premise, measured before anything is asserted about the
        subject: this is a real override, not a hypothetical one."""
        self.write(os.path.join(self.checkout, ".gitattributes"),
                   SANDBOX_GITATTRIBUTES + "*.mp4 text\n")
        self.assertEqual(
            self.effective("playthrough/cata-play.mp4", "text"), "set")

    def test_a_later_override_in_the_working_tree_is_refused(self):
        """The ruleset THIS run's `git add` would apply."""
        self.take_creation()
        self.play_session()
        self.write(os.path.join(self.checkout, ".gitattributes"),
                   SANDBOX_GITATTRIBUTES + "*.mp4 text\n")
        message = self.refuse(EX_PREREQ, ("final",))
        self.assertIn("playthrough/cata-play.mp4", message)
        self.assertIn("LAST matching pattern", message)
        self.assertIn("Nothing was committed", message)

    def test_a_later_override_in_the_history_is_refused(self):
        """The ruleset a fresh clone would get.

        Committed, with the working tree left carrying the same file, so
        what is refused is HEAD's own answer.
        """
        if not self.check_attr_reads_a_tree():
            self.skipTest("this git cannot be asked about a tree-ish "
                          "('git check-attr --source' arrived in 2.40)")
        self.commit_worktree_file(
            ".gitattributes", SANDBOX_GITATTRIBUTES + "*.srt -text\n")
        message = self.refuse(EX_PREREQ, ("creation",))
        self.assertIn("playthrough/transcript.srt", message)
        self.assertIn("text: unset", message)

    def test_an_override_by_directory_pattern_is_caught_too(self):
        """A row need not name a suffix to override one.

        This is what a row-by-row check cannot see at all: every declared
        row is still present and spelled exactly right.
        """
        self.take_creation()
        self.play_session()
        self.write(os.path.join(self.checkout, ".gitattributes"),
                   SANDBOX_GITATTRIBUTES + "playthrough/** text\n")
        message = self.refuse(EX_PREREQ, ("final",))
        for row in REQUIRED_ATTRIBUTE_ROWS:
            self.assertNotIn("carries no '%s' row" % row, message)
        self.assertIn("git would apply", message)

    def test_the_integration_milestone_will_not_publish_an_override(self):
        """It commits these two files, so it checks them hardest."""
        self.write(os.path.join(self.checkout, ".gitattributes"),
                   SANDBOX_GITATTRIBUTES + "*.gsav text\n")
        message = self.refuse(EX_PREREQ, ("integration",))
        self.assertIn("master.gsav", message)

    def test_a_clean_ruleset_is_reported_as_applying(self):
        _, err = self.take_creation()
        self.assertIn("git applies this feature's attributes", err)

    def check_attr_reads_a_tree(self):
        """Whether this git supports --source, asked of this git."""
        result = subprocess.run(
            [os.path.join(self.bin, "git"), "check-attr",
             "--source=HEAD", "text", "--", ".gitattributes"],
            cwd=self.checkout, capture_output=True,
            env={"PATH": self.bin,
                 "GIT_CONFIG_GLOBAL": self.global_config,
                 "GIT_CONFIG_NOSYSTEM": "1"},
            timeout=60)
        return result.returncode == 0


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
        for name in ("integration", "dossier", "creation", "final",
                     "status", "help"):
            with self.subTest(subcommand=name):
                self.assertIn(name, out)
        self.assertIn("stdout carries KEY=value lines only", out)

    def help_prose(self):
        """The help text as prose: lowercased, whitespace collapsed.

        The block is hard-wrapped at 79 columns, so a phrase of more than
        a word or two straddles a newline and a literal substring test
        fails on the wrapping rather than on the content.  Collapsing
        first asserts what the text SAYS, which is the thing worth
        pinning; the wrapping is free to change.
        """
        _, out, _ = self.run_script(("help",))
        return " ".join(out.lower().split())

    def test_the_help_states_the_ordering_the_lifecycle_enforces(self):
        """Four steps that refuse out of turn are only usable if the
        order is written down where somebody looks for it."""
        prose = self.help_prose()
        self.assertIn("integration -> dossier -> creation -> play the "
                      "session -> final", prose)
        self.assertIn("checked as ancestry between two commits", prose)
        self.assertIn("one commit cannot precede itself", prose)

    def test_the_help_says_which_step_commits_the_rule_files(self):
        """An operator who never reads the source still has to end up
        with the negation committed, or the save data is absent from the
        next clone while every check in the working tree passes."""
        prose = self.help_prose()
        self.assertIn("commit .gitignore and .gitattributes, and "
                      "nothing else", prose)
        self.assertIn("!/playthrough/**", prose)
        self.assertIn("it is idempotent", prose)

    def test_the_help_says_it_writes_no_configuration_at_all(self):
        """And says where the container's identity comes from instead.

        The help went back and forth on this, and the round trip is worth
        recording.  It said "never writes git configuration"; then the
        container was found to have no identity at all, and the help was
        changed to describe the `git config --local` write that fixed
        that; then the write itself was found to contradict the script's
        own contract and to be forbidden outright by the environment this
        evidence is produced in.  So the claim is back to "never" -- and
        this time it has to be accompanied by the mechanism that replaced
        it, or an operator reading it will reintroduce the write the next
        time a checkpoint inside the image cannot find an author.
        """
        # help_prose() LOWERCASES as well as collapsing whitespace, so
        # the emphasis this text carries in capitals has to be matched in
        # lower case.  Asserting the capitals reads as absent content.
        prose = self.help_prose()
        self.assertIn("it never writes git configuration", prose)
        self.assertIn("git_author_", prose)
        self.assertIn("supported_env.sh", prose)
        self.assertIn("never invents an identity", prose)
        # And the retired write is not still advertised as current.
        self.assertNotIn("git config --local, never --global and never "
                         "--system", prose)
        # And what it does when the repository already records a pair,
        # which is the half a reader would otherwise have to guess at.
        self.assertIn("already matches is left as found", prose)
        self.assertIn("disagrees", prose)
        # And that a disagreement is refused rather than corrected, which
        # is the half that changed.
        self.assertIn("a refusal, not a rewrite", prose)

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
