#!/usr/bin/env python3
"""Smoke suite for the commands playthrough/README.md documents.

    python3 -B playthrough/tooling/test_readme.py
    python3 -B -m unittest discover -s playthrough/tooling -p 'test_*.py'

WHAT THIS SUITE IS FOR
Every other suite in this directory tests code.  This one tests the
PAGE.  The `console` examples in playthrough/README.md are the
operator's entry point, and a page that names a renamed flag, a moved
script or a count that has since changed is worse than no page at all:
it gets followed, and it fails on a stranger's afternoon rather than
here.  Nothing was checking them.

So every documented example is held to whichever of three contracts it
can honestly be held to.

* IT PARSES, AND ITS PATHS RESOLVE.  Each `$ ` command is joined across
  its backslash continuations and handed to `bash -n`, so a quoting or
  continuation error on the page is a failure here.  Every repository
  path any command names must exist -- a glob must match at least one
  file -- and must be tracked by git or deliberately ignored by it.
  The `bash` blocks are parsed the same way.  Nothing in this group
  runs.
* THE PAGE AND THE SCRIPT AGREE.  Every subcommand and option the page
  names for the five entry points must be one that entry point's own
  help text lists, measured by running the documented help form.  A
  flag renamed in a script without the page following is caught here.
* THE QUOTED OUTPUT IS STILL TRUE.  Where the page quotes what a
  command printed, the command is run and its output is compared with
  the quotation -- exactly where the value is a property of the
  committed record (the capture and row counts, the timeline totals,
  the final cue, the caption stream, the pinned requirements, the
  ignore and attribute rules, the committed config listing, the
  survivor's save file), and whitespace-collapsed where the page
  reflowed a line to fit its column.

WHAT IT DELIBERATELY DOES NOT RUN.  A stated boundary, not an
oversight:

* Anything that MUTATES: `commit_artifacts.sh` other than `status`,
  `run_pipeline.sh` without `--help`, `session.py step`,
  `launch_game.sh` other than `help`, and `python3 -m venv /tmp/probe`.
* Anything needing THE GAME or A DISPLAY: every launch and capture
  example.
* Anything needing DOCKER: every `supported_env.sh` subcommand.  Its
  usage text is still read, so the page's subcommand names are checked.
* Anything whose value is a fact about THE HOST rather than about the
  record: `python3 -V`, the EXTERNALLY-MANAGED marker, `apt-cache
  policy`, `pkg-config --exists sdl3`, and the interpreter-path and
  platform lines of the environment report.  Their KEYS are asserted;
  their host-specific VALUES are not.
* Two counts that drift BY DESIGN, and are therefore quoted on the page
  but not asserted here: `git rev-list --count` moves with every
  commit, and `git ls-files playthrough | wc -l` moves with every
  tooling file added.  They are maintained by hand, and this docstring
  is where a reader is told which two those are.
* The tiles binary's version hash, which names whichever commit that
  particular build came from.  `+tiles` is the line that carries the
  claim, and that line is asserted.

It imports only the standard library.  It writes nothing anywhere in
the repository -- proved per test by re-walking playthrough/ afterwards
and by refusing any bytecode beside these modules -- and it needs no
waiver: every example it runs is run with PLAYTHROUGH_ALLOW_EOL_PLATFORM
and every other PLAYTHROUGH_ variable REMOVED from the child
environment, which is itself the page's claim that its read-only
examples work on a plain checkout.
"""

import ast
import collections
import fnmatch
import glob
import os
import re
import shlex
import shutil
import subprocess
import sys
import unittest

TOOLING = os.path.dirname(os.path.abspath(__file__))
PLAYTHROUGH = os.path.dirname(TOOLING)
ROOT = os.path.dirname(PLAYTHROUGH)
README = os.path.join(PLAYTHROUGH, "README.md")

FENCE = "```"
PROMPT = "$ "
LANGUAGES = ("console", "bash", "text")
TIMEOUT = 900

# Floors, not exact counts: the page may grow, and a parser that
# silently found nothing must fail rather than pass vacuously.
LEAST_CONSOLE_BLOCKS = 25
LEAST_COMMANDS = 55
LEAST_PATHS = 20

# Named on the page as git-ignored and tracked in no commit, so a
# checkout has none and "it must exist" is the wrong assertion.
# Every one of these is asserted untracked AND ignored below, which is
# what keeps the list from becoming a way to excuse a path the page got
# wrong: the page tells a reader to BUILD or INSTALL each of them, so a
# fresh clone is not expected to carry it.
#   cataclysm-tiles                 the tiles binary, built by make
#   gfx/MShockXotto+                the artwork pack, composed and
#                                   installed by the page's own recipe;
#                                   gfx/ is excluded wholesale
#                                   [.gitignore:52], which is why the
#                                   tracked provenance anchor exists
#   tools/format/json_formatter.cgi the formatter that recipe builds
#                                   first, a make target of this
#                                   repository rather than a file in it
BUILD_PRODUCTS = ("cataclysm-tiles", "gfx/MShockXotto+",
                  "tools/format/json_formatter.cgi")

# Documented examples this suite must never execute.  Each mutates the
# repository, needs the game or a display, needs docker, takes minutes,
# or measures the host rather than the record.  Enforced at run time in
# ExampleFixture.shell, because the command text comes from the page.
REFUSED = (
    "commit_artifacts.sh integration",
    "commit_artifacts.sh dossier",
    "commit_artifacts.sh creation",
    "commit_artifacts.sh final",
    "run_pipeline.sh --no-commit",
    "run_pipeline.sh --from",
    "run_pipeline.sh --only",
    "verify_artifacts.sh --phase",
    "session.py step",
    "launch_game.sh all",
    "supported_env.sh build",
    "supported_env.sh inventory",
    "supported_env.sh preflight",
    "supported_env.sh run",
    "supported_env.sh shell",
    "-m venv",
    "apt-cache",
    "pkg-config",
    "EXTERNALLY-MANAGED",
)

# Environment-report values that are properties of the CONTRACT rather
# than of the host, so the page may be held to them exactly.
CONTRACT_KEYS = (
    "DISPLAY",
    "SDL_VIDEODRIVER",
    "SDL_AUDIODRIVER",
    "LIBGL_ALWAYS_SOFTWARE",
    "PYTHONDONTWRITEBYTECODE",
    "PLAYTHROUGH_SCREEN",
    "PLAYTHROUGH_WINDOW_CLASS",
    "PLAYTHROUGH_TILESET",
    "PLAYTHROUGH_SIDEBAR_LAYOUT",
    "PLAYTHROUGH_SIDEBAR_CELLS",
    "PLAYTHROUGH_USERDIR_ARG",
)

_TOP_LEVEL = ("playthrough", "data", "src", "gfx", "tools", "doc",
              "lang", "build-scripts", "tests")
_PATH = re.compile(r"(?<![\w./-])(?:\./)?((?:" + "|".join(_TOP_LEVEL) +
                   r")/[A-Za-z0-9_./*+=#-]+)")
_ROOT_FILE = re.compile(r"(?<![\w.-])(?:\./)?"
                        r"(cataclysm-tiles|Makefile|\.gitignore"
                        r"|\.gitattributes)(?![\w./-])")
_RECTANGLE = re.compile(r"^\d+x\d+\+\d+\+\d+$")

Block = collections.namedtuple("Block", "language first lines")
Example = collections.namedtuple("Example", "command output line block")

_PAGE = None
_BLOCKS = None
_EXAMPLES = None


def page():
    """The README as text, decoded strictly so mojibake cannot pass."""
    global _PAGE
    if _PAGE is None:
        with open(README, "rb") as handle:
            _PAGE = handle.read().decode("utf-8")
    return _PAGE


def fence_lines():
    """Every fence line as (number, stripped text), indented or not."""
    found = []
    for number, line in enumerate(page().split("\n"), 1):
        stripped = line.strip()
        if stripped.startswith(FENCE):
            found.append((number, stripped))
    return tuple(found)


def blocks():
    """Every fenced block, dedented to the opening fence's indent.

    Two of this page's blocks sit inside list items and are therefore
    indented; a parser that only recognised column-zero fences would
    silently drop them, which is the kind of quiet gap this suite
    exists to refuse.
    """
    global _BLOCKS
    if _BLOCKS is not None:
        return _BLOCKS
    parsed = []
    language = None
    indent = ""
    body = []
    first = 0
    for number, line in enumerate(page().split("\n"), 1):
        stripped = line.strip()
        if language is None:
            if stripped.startswith(FENCE):
                language = stripped[len(FENCE):].strip()
                indent = line[:len(line) - len(line.lstrip())]
                body = []
                first = number
            continue
        if stripped == FENCE:
            parsed.append(Block(language, first, tuple(body)))
            language = None
            continue
        if indent and line.startswith(indent):
            body.append(line[len(indent):])
        else:
            body.append(line)
    if language is not None:
        parsed.append(Block(language, first, tuple(body)))
    _BLOCKS = tuple(parsed)
    return _BLOCKS


def console_examples():
    """Each prompted command with the lines the page quotes under it.

    A command is joined across its continuations by KEEPING the
    backslash-newline, because that is what bash itself reads: the text
    handed to `bash -c` here is byte-for-byte what a reader would paste.
    """
    global _EXAMPLES
    if _EXAMPLES is not None:
        return _EXAMPLES
    found = []
    for block in blocks():
        if block.language != "console":
            continue
        lines = block.lines
        index = 0
        while index < len(lines):
            if not lines[index].startswith(PROMPT):
                index += 1
                continue
            command = [lines[index][len(PROMPT):]]
            at = block.first + 1 + index
            index += 1
            while command[-1].endswith("\\") and index < len(lines):
                command.append(lines[index])
                index += 1
            output = []
            while (index < len(lines) and
                   not lines[index].startswith(PROMPT)):
                output.append(lines[index])
                index += 1
            found.append(Example("\n".join(command), tuple(output), at,
                                 block.first))
    _EXAMPLES = tuple(found)
    return _EXAMPLES


def documented_paths():
    """Every repository path any documented command names."""
    found = {}
    for example in console_examples():
        for match in _PATH.finditer(example.command):
            found.setdefault(match.group(1), []).append(example)
        for match in _ROOT_FILE.finditer(example.command):
            found.setdefault(match.group(1), []).append(example)
    return found


def collapse(text):
    """Whitespace-insensitive form, for lines the page reflowed."""
    return " ".join(text.split())


def without_note(command):
    """A command with the page's trailing `  # note` removed.

    The page annotates several commands with an aligned comment, so the
    same invocation appears both bare and annotated.  Two spaces before
    the hash is what distinguishes a note from a hash inside an
    argument, as in `grep -vE '^\\s*(#|$)'`.
    """
    return re.sub(r"\s{2,}#\s.*$", "", command).rstrip()


def tail(text, limit=1200):
    return text[-limit:] if len(text) > limit else text


def child_environment():
    """The environment the page's examples are entitled to assume.

    Every PLAYTHROUGH_ variable is removed, so an example runs against
    the documented defaults rather than against this shell's state --
    including PLAYTHROUGH_ALLOW_EOL_PLATFORM, which makes "the
    read-only examples need no waiver" a measured claim.
    PYTHONDONTWRITEBYTECODE is removed too, so what keeps bytecode out
    of the tree during these runs is the tooling's own
    `sys.dont_write_bytecode` plus the `-B` the page writes into every
    Python command -- not this suite's inherited environment.
    """
    environment = dict(os.environ)
    for name in list(environment):
        if name.startswith("PLAYTHROUGH_"):
            del environment[name]
    environment.pop("PYTHONDONTWRITEBYTECODE", None)
    environment["LC_ALL"] = "C.UTF-8"
    return environment


def walk_playthrough():
    """Size and mtime of every file under playthrough/, for residue."""
    seen = {}
    for base, _, names in os.walk(PLAYTHROUGH):
        for name in names:
            path = os.path.join(base, name)
            try:
                stat = os.stat(path)
            except OSError:
                seen[path] = None
                continue
            seen[path] = (stat.st_size, stat.st_mtime_ns)
    return seen


def git(*arguments):
    """A read-only git call in the checkout, as text."""
    return subprocess.run(
        ["git"] + list(arguments), cwd=ROOT, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, timeout=TIMEOUT,
        universal_newlines=True)


class TestThePageParses(unittest.TestCase):
    """The page is readable, and this suite's reading of it is sound.

    Every later class trusts the parser above, so the parser is held to
    the page first: an unclosed fence, an unlabelled block, a prompt
    written some other way or a continuation left dangling would all
    make the groups below measure less than they appear to.
    """

    def test_the_page_decodes_as_utf8_and_carries_real_content(self):
        text = page()
        self.assertGreater(len(text), 40000,
                           "playthrough/README.md is far shorter than "
                           "the page this suite was written against")
        self.assertNotIn("\ufffd", text,
                         "the page contains a replacement character, "
                         "so something was written through the wrong "
                         "codec")
        self.assertNotIn("\r", text, "the page carries CRLF endings")

    def test_every_fence_is_paired_and_the_openers_are_labelled(self):
        fences = fence_lines()
        self.assertEqual(len(fences) % 2, 0,
                         "odd number of fence lines, so a block is "
                         "unterminated: %s" % (fences,))
        for position, (number, text) in enumerate(fences):
            with self.subTest(line=number):
                if position % 2:
                    self.assertEqual(text, FENCE,
                                     "closing fence carries text")
                else:
                    self.assertIn(text[len(FENCE):].strip(), LANGUAGES,
                                  "opening fence has no known language")

    def test_the_page_documents_the_body_of_examples_it_used_to(self):
        console = [b for b in blocks() if b.language == "console"]
        self.assertGreaterEqual(len(console), LEAST_CONSOLE_BLOCKS)
        self.assertGreaterEqual(len(console_examples()), LEAST_COMMANDS)
        self.assertGreaterEqual(len(documented_paths()), LEAST_PATHS)

    def test_the_indented_blocks_are_read_too(self):
        # Two blocks sit inside list items.  If the parser ever loses
        # them it loses them silently, so their presence is asserted.
        indented = [n for n, _ in fence_lines()
                    if page().split("\n")[n - 1].startswith(" ")]
        self.assertTrue(indented,
                        "no indented fence found, so this assertion "
                        "no longer proves the parser dedents")
        for number in indented:
            with self.subTest(line=number):
                self.assertTrue(
                    any(b.first == number or
                        b.first < number <= b.first + len(b.lines) + 1
                        for b in blocks()),
                    "an indented fence was not parsed into a block")

    def test_every_console_block_carries_at_least_one_command(self):
        for block in blocks():
            if block.language != "console":
                continue
            with self.subTest(line=block.first):
                self.assertTrue(
                    [ln for ln in block.lines
                     if ln.startswith(PROMPT)],
                    "a console block quotes output with no command")

    def test_every_prompt_is_written_as_a_dollar_and_a_space(self):
        for block in blocks():
            if block.language != "console":
                continue
            for offset, line in enumerate(block.lines):
                if not line.startswith("$"):
                    continue
                with self.subTest(line=block.first + 1 + offset):
                    self.assertTrue(line.startswith(PROMPT),
                                    "prompt written as %r" % line[:8])

    def test_no_command_is_blank_or_left_continuing(self):
        for example in console_examples():
            with self.subTest(line=example.line):
                self.assertTrue(example.command.strip(),
                                "an empty prompted line")
                self.assertFalse(
                    example.command.rstrip().endswith("\\"),
                    "the command's last line still continues, so the "
                    "block ended mid-command")

    def test_every_documented_python_command_carries_dash_b(self):
        # The page states this of itself, and the reason is specific:
        # bytecode under this tree is RE-INCLUDED by the terminal
        # `!/playthrough/**` negation, so a command that invited it
        # would end up committing it.  Every invocation through the
        # resolved interpreter is held to it.
        found = 0
        for example in console_examples():
            # The quoted form is the INVOCATION; the bare name also
            # appears as a grep pattern in the environment report.
            if '"$PLAYTHROUGH_PYTHON"' not in example.command:
                continue
            found += 1
            with self.subTest(line=example.line):
                self.assertIn(" -B ", example.command,
                              "a documented Python command without -B")
        self.assertGreaterEqual(found, 8,
                                "the page's Python examples have gone "
                                "missing from this check")

    def test_no_documented_command_sets_the_banned_video_driver(self):
        # SDL_VIDEODRIVER=dummy renders nothing and would produce a
        # black film; the audio driver is a different variable.
        for example in console_examples() + tuple(
                Example("\n".join(b.lines), (), b.first, b.first)
                for b in blocks() if b.language == "bash"):
            with self.subTest(line=example.line):
                self.assertNotIn("SDL_VIDEODRIVER=dummy",
                                 example.command)


class TestEveryPathThePageNamesResolves(unittest.TestCase):
    """A command that names a moved file is a broken instruction."""

    @classmethod
    def setUpClass(cls):
        listing = git("ls-files", "-z", "--", "playthrough", "data",
                      "src", "gfx", "tools", "doc", "lang", "tests",
                      ".gitignore", ".gitattributes", "Makefile")
        cls.tracked = tuple(
            entry for entry in listing.stdout.split("\0") if entry)

    def is_tracked(self, path):
        wanted = path.rstrip("/")
        for entry in self.tracked:
            if entry == wanted or entry.startswith(wanted + "/"):
                return True
            if fnmatch.fnmatch(entry, wanted):
                return True
        return False

    def test_every_path_a_command_names_exists_on_disk(self):
        for path, examples in sorted(documented_paths().items()):
            if path in BUILD_PRODUCTS:
                continue
            with self.subTest(path=path,
                              line=examples[0].line):
                if any(mark in path for mark in "*?["):
                    self.assertTrue(
                        glob.glob(os.path.join(ROOT, path)),
                        "the glob matches nothing in this checkout")
                else:
                    self.assertTrue(
                        os.path.exists(os.path.join(ROOT, path)),
                        "the page names a path that is not here")

    def test_every_path_a_command_names_is_tracked_by_git(self):
        for path, examples in sorted(documented_paths().items()):
            if path in BUILD_PRODUCTS:
                continue
            with self.subTest(path=path, line=examples[0].line):
                self.assertTrue(
                    self.is_tracked(path),
                    "the page documents a path no commit carries, so "
                    "a fresh clone following this page would not "
                    "have it")

    def test_the_build_products_it_calls_untracked_are_untracked(self):
        for name in BUILD_PRODUCTS:
            with self.subTest(product=name):
                self.assertFalse(self.is_tracked(name))
                ignored = git("check-ignore", "-q", "--", name)
                self.assertEqual(
                    ignored.returncode, 0,
                    "%s is neither tracked nor ignored, so the page's "
                    "account of it is wrong" % name)

    def test_every_tooling_file_is_named_somewhere_on_the_page(self):
        # `assertIn` against the whole page would print the whole page
        # on failure, so the membership test is done by hand.
        text = page()
        for name in sorted(os.listdir(TOOLING)):
            if name.startswith("test_"):
                continue
            if not os.path.isfile(os.path.join(TOOLING, name)):
                continue
            with self.subTest(name=name):
                self.assertTrue(name in text,
                                "the page never names the tooling file "
                                "%s, so a reader cannot find it" % name)

    def test_the_page_counts_the_suites_that_are_actually_here(self):
        suites = sorted(os.path.basename(path) for path in
                        glob.glob(os.path.join(TOOLING, "test_*.py")))
        claims = re.findall(r"(\d+) `test_\*\.py` suites", page())
        claims += re.findall(r"(\d+) in all", page())
        self.assertEqual(len(claims), 2,
                         "the page used to state the suite count in "
                         "two places -- the directory table and the "
                         "testing section -- and now states %s"
                         % (claims,))
        for claim in claims:
            with self.subTest(claim=claim):
                self.assertEqual(int(claim), len(suites),
                                 "the page counts %s suites; %d are "
                                 "here: %s" % (claim, len(suites),
                                               suites))


class TestEveryDocumentedCommandIsValidShell(unittest.TestCase):
    """`bash -n` parses without running, so this group is inert."""

    def parses(self, text, where):
        proc = subprocess.run(
            ["bash", "-n", "-c", text], cwd=ROOT,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=TIMEOUT, universal_newlines=True)
        self.assertEqual(
            proc.returncode, 0,
            "the command at README line %s does not parse:\n%s\n%s"
            % (where, text, tail(proc.stderr)))

    def test_every_prompted_command_parses_as_bash(self):
        for example in console_examples():
            with self.subTest(line=example.line):
                self.parses(example.command, example.line)

    def test_every_bash_block_parses_as_bash(self):
        found = 0
        for block in blocks():
            if block.language != "bash":
                continue
            found += 1
            with self.subTest(line=block.first):
                self.parses("\n".join(block.lines), block.first)
        self.assertGreaterEqual(found, 3,
                                "the page's shell snippets have gone "
                                "missing from this check")


class ExampleFixture(unittest.TestCase):
    """Runs documented examples, and proves the run changed nothing.

    Every example reached from here is read-only by construction -- the
    mutating ones are listed in this module's docstring and are never
    invoked -- so "nothing under playthrough/ changed" is checked after
    each test rather than trusted.
    """

    def setUp(self):
        self.before = walk_playthrough()

    def tearDown(self):
        after = walk_playthrough()
        if after != self.before:
            appeared = sorted(set(after) - set(self.before))
            vanished = sorted(set(self.before) - set(after))
            altered = sorted(name for name in set(after) & set(
                self.before) if after[name] != self.before[name])
            self.fail("running a documented example changed the tree; "
                      "this suite must be read-only.\nappeared: %s\n"
                      "vanished: %s\naltered: %s"
                      % (appeared, vanished, altered))
        self.assertFalse(
            os.path.isdir(os.path.join(TOOLING, "__pycache__")),
            "a documented example wrote bytecode into "
            "playthrough/tooling/, so both guards failed at once -- "
            "the module's own sys.dont_write_bytecode and the -B the "
            "page writes into every Python command")

    def all_documented(self, fragment):
        """Every documented command containing `fragment`, in order."""
        found = [example for example in console_examples()
                 if fragment in example.command]
        self.assertTrue(found,
                        "no documented command contains %r any more, "
                        "so the page was edited without updating this "
                        "suite" % fragment)
        return found

    def documented(self, fragment):
        """The one documented command containing `fragment`."""
        found = self.all_documented(fragment)
        self.assertEqual(len(found), 1,
                         "expected exactly one documented command "
                         "containing %r, found %d at README lines %s"
                         % (fragment, len(found),
                            [example.line for example in found]))
        return found[0]

    def documented_exactly(self, command):
        """The documented command whose text is exactly `command`."""
        found = [example for example in console_examples()
                 if example.command == command]
        self.assertEqual(len(found), 1,
                         "expected exactly one documented command "
                         "written as %r, found %d"
                         % (command, len(found)))
        return found[0]

    def shell(self, command, status=0):
        """Run a documented command the way a reader would paste it.

        The deny-list is a runtime guard rather than a comment: the
        command text comes from the page, so a page edit could otherwise
        walk a mutating example into this suite.  Anything that commits,
        renders, launches, keys the game, builds an image or probes the
        host is refused here, loudly.
        """
        for banned in REFUSED:
            self.assertNotIn(
                banned, command,
                "this suite refuses to run %r: it mutates the "
                "repository, needs the game, needs docker, or measures "
                "the host rather than the record" % banned)
        runnable = command.replace('"$PLAYTHROUGH_PYTHON"',
                                   shlex.quote(sys.executable))
        proc = subprocess.run(
            ["bash", "-c", runnable], cwd=ROOT,
            env=child_environment(), stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=TIMEOUT,
            universal_newlines=True)
        self.assertEqual(
            proc.returncode, status,
            "`%s` exited %d rather than %d\n--- stdout ---\n%s\n"
            "--- stderr ---\n%s"
            % (runnable, proc.returncode, status, tail(proc.stdout),
               tail(proc.stderr)))
        return proc

    def run_documented(self, fragment, status=0):
        example = self.documented(fragment)
        return example, self.shell(example.command, status)

    def quoted_rectangle(self, example):
        """The crop rectangle the page quotes under a command."""
        found = [line for line in example.output
                 if _RECTANGLE.match(line.strip())]
        self.assertEqual(len(found), 1,
                         "expected one rectangle in the quotation at "
                         "README line %d, found %s"
                         % (example.line, found))
        return found[0].strip()

    def names_on_page(self, pattern):
        """Every distinct name the page uses in `pattern`."""
        found = sorted(set(re.findall(pattern, page())))
        self.assertTrue(found,
                        "the page no longer names anything matching "
                        "%r" % pattern)
        return found


class TestThePageAndTheScriptsAgree(ExampleFixture):
    """A flag renamed in a script without the page following.

    Each entry point is asked for its own help text, and every
    subcommand or option THE PAGE names for it has to appear there.  The
    direction matters: a script may offer more than the page documents,
    but the page may not document something the script does not offer.
    """

    def check_help(self, command, names, status=0):
        proc = self.shell(command, status)
        text = proc.stdout + proc.stderr
        self.assertTrue(text.strip(),
                        "`%s` printed nothing" % command)
        for name in names:
            with self.subTest(name=name):
                self.assertTrue(
                    name in text,
                    "the page documents %r for `%s`, which its own "
                    "help text does not mention" % (name, command))
        return text

    def test_the_sequencer_documents_every_option_the_page_uses(self):
        example = self.documented("run_pipeline.sh --help")
        options = self.names_on_page(r"run_pipeline\.sh (--[a-z-]+)")
        stages = self.names_on_page(r"run_pipeline\.sh --(?:from|only)"
                                    r" ([a-z]+)")
        self.check_help(example.command, options + stages)

    def test_the_launcher_lists_every_subcommand_the_page_uses(self):
        example = self.documented("launch_game.sh help")
        self.check_help(example.command,
                        self.names_on_page(
                            r"launch_game\.sh ([a-z][a-z-]*)"))

    def test_the_gate_documents_every_option_the_page_uses(self):
        options = self.names_on_page(
            r"verify_artifacts\.sh (--[a-z-]+)")
        phases = self.names_on_page(
            r"verify_artifacts\.sh --phase ([a-z-]+)")
        self.check_help("playthrough/tooling/verify_artifacts.sh "
                        "--help", options + phases)

    def test_the_committer_lists_every_checkpoint_the_page_uses(self):
        self.check_help("playthrough/tooling/commit_artifacts.sh "
                        "--help",
                        self.names_on_page(
                            r"commit_artifacts\.sh ([a-z][a-z-]*)"))

    def test_the_container_driver_lists_the_page_subcommands(self):
        # Its subcommands need docker to RUN; its usage text does not.
        self.check_help("playthrough/tooling/supported_env.sh help",
                        self.names_on_page(
                            r"supported_env\.sh ([a-z][a-z-]*)"))

    def test_the_session_tool_lists_every_subcommand_the_page_uses(
            self):
        self.check_help("%s -B playthrough/tooling/session.py --help"
                        % shlex.quote(sys.executable),
                        self.names_on_page(
                            r"session\.py ([a-z][a-z-]*)"))


class TestTheQuotedOutputIsStillTrue(ExampleFixture):
    """Where the page quotes what a command printed, it is re-run.

    These are the figures a reviewer would take at face value, so each
    is compared with the quotation itself rather than with a literal
    written here -- edit the page and this suite measures the new claim,
    which is the only arrangement that cannot drift.
    """

    def test_the_pinned_requirements_are_exactly_what_it_quotes(self):
        example, proc = self.run_documented("requirements.txt")
        self.assertEqual(proc.stdout.splitlines(),
                         list(example.output))

    def test_the_capture_and_row_counts_are_what_it_quotes(self):
        for fragment in ("frames/frame_*.png | wc -l",
                         "wc -l < playthrough/manifest.jsonl"):
            with self.subTest(command=fragment):
                example, proc = self.run_documented(fragment)
                self.assertEqual(proc.stdout.split(),
                                 list(example.output))

    def test_the_tracked_counts_are_what_it_quotes(self):
        for fragment in ("git ls-files playthrough/frames",
                         "git ls-files playthrough/userdir/save"):
            with self.subTest(command=fragment):
                example, proc = self.run_documented(fragment)
                self.assertEqual(proc.stdout.split(),
                                 list(example.output))

    def test_the_timeline_invariant_is_what_it_quotes(self):
        example, proc = self.run_documented("total_duration")
        self.assertEqual(proc.stdout.split(),
                         example.output[0].split())
        duration, transition, total, cue = [
            float(value) for value in proc.stdout.split()]
        self.assertAlmostEqual(duration + transition, total, places=3)
        self.assertAlmostEqual(total, cue, places=3)

    def test_the_final_cue_is_what_it_quotes(self):
        example, proc = self.run_documented("tail -1")
        self.assertEqual(collapse(proc.stdout),
                         collapse(example.output[0]))

    def test_the_sidebar_preset_spread_is_what_it_quotes(self):
        example, proc = self.run_documented("sidebar*.json | wc -l")
        self.assertEqual(proc.stdout.split(), list(example.output))
        example, proc = self.run_documented("ls -d data/json/ui")
        self.assertEqual(sorted(proc.stdout.split()),
                         sorted(" ".join(example.output).split()))

    def test_the_committed_config_listing_is_what_it_quotes(self):
        example, proc = self.run_documented(
            "ls -1 playthrough/userdir/config/")
        self.assertEqual(proc.stdout.split(), list(example.output))
        # The page's R12 evidence is this listing's ABSENCE of one name.
        self.assertNotIn("keybindings.json", proc.stdout)

    def test_the_survivor_save_file_is_what_it_quotes(self):
        # The survivor died, so the engine moved the character files into
        # userdir/graveyard/<timestamp>/; that is where the page quotes
        # the save file from, and it is the same assertion either way --
        # the listing the page prints is the listing the tree gives.
        example, proc = self.run_documented("| grep -E '^#.*\\.sav$'")
        self.assertEqual(proc.stdout.split(), list(example.output))

    def test_the_world_option_it_quotes_is_still_false(self):
        example, proc = self.run_documented("WORLD_COMPRESSION2")
        self.assertIn("'name': 'WORLD_COMPRESSION2'", proc.stdout)
        self.assertIn("'value': 'false'", proc.stdout)
        # The quotation elides the middle keys with an ellipsis, so the
        # two ends of it are what can honestly be compared.
        self.assertTrue(example.output[0].startswith(
            "[{'name': 'WORLD_COMPRESSION2'"))

    def test_the_rule_that_hides_the_binary_is_what_it_quotes(self):
        example, proc = self.run_documented(
            "check-ignore -v cataclysm-tiles")
        self.assertEqual(collapse(proc.stdout),
                         collapse(example.output[0]))

    def test_the_binary_is_in_no_commit_exactly_as_it_says(self):
        example, proc = self.run_documented("--error-unmatch", 1)
        self.assertIn("did not match any file", proc.stderr)
        self.assertIn("did not match any file",
                      "\n".join(example.output))

    def test_the_negation_that_rescues_the_save_is_quoted_right(self):
        example, proc = self.run_documented("--no-index")
        quoted = collapse(example.output[0])
        prefix = quoted.split("\u2026")[0]
        self.assertTrue(
            collapse(proc.stdout).startswith(prefix),
            "the rule that re-includes the save now reads %r, not %r"
            % (collapse(proc.stdout), quoted))

    def test_the_branch_base_is_still_the_commit_it_names(self):
        example, proc = self.run_documented("git log -1")
        self.assertEqual(proc.stdout.splitlines(),
                         list(example.output))
        example, proc = self.run_documented("--is-ancestor")
        self.assertEqual(proc.stdout.splitlines(),
                         list(example.output))

    def test_the_change_surface_outside_playthrough_is_quoted_right(
            self):
        example, proc = self.run_documented("':(exclude)playthrough'")
        self.assertEqual([collapse(line) for line
                          in proc.stdout.splitlines()],
                         [collapse(line) for line in example.output])
        example, proc = self.run_documented("--shortstat")
        self.assertEqual(collapse(proc.stdout),
                         collapse(example.output[0]))

    def test_the_attribute_rows_added_are_what_it_quotes(self):
        example, proc = self.run_documented("grep '^+[^+]'")
        self.assertEqual([collapse(line) for line
                          in proc.stdout.splitlines()],
                         [collapse(line) for line in example.output])

    @unittest.skipUnless(shutil.which("ffprobe"),
                         "ffprobe is not installed on this host")
    def test_the_caption_stream_is_what_it_quotes(self):
        example, proc = self.run_documented("cata-play-cc.mp4")
        self.assertEqual(proc.stdout.split(), list(example.output))

    def test_the_binary_reports_the_tiles_build_it_quotes(self):
        if not os.path.exists(os.path.join(ROOT, "cataclysm-tiles")):
            self.skipTest("this checkout has not built the binary; "
                          "the page documents that as expected")
        # THE PAGE NAMES THIS COMMAND MORE THAN ONCE, and only one of
        # them is the example: it also shows what a fresh clone gets
        # instead (a shell error, no binary) and uses it inside the
        # `git diff` probe that asks whether the engine has moved since
        # the build.  The one under test is the block that QUOTES the
        # build banner, which is what this test is about.
        examples = [example
                    for example in self.all_documented(
                        "./cataclysm-tiles --version")
                    if "+tiles, +sound" in "\n".join(example.output)]
        self.assertEqual(
            len(examples), 1,
            "exactly one documented block quotes the build banner; "
            "found %d at README lines %s"
            % (len(examples), [example.line for example in examples]))
        example = examples[0]
        proc = self.shell(example.command)
        # The version hash names whichever commit that build came from
        # and differs between builds; `+tiles` is the claim.
        self.assertIn("+tiles, +sound", example.output)
        self.assertIn("+tiles, +sound", proc.stdout.splitlines())


class TestTheReadOnlyToolExamplesRun(ExampleFixture):
    """The examples that invoke the pipeline's own read-only modes."""

    def test_the_geometry_module_prints_the_rectangle_it_quotes(self):
        examples = self.all_documented("sidebar_geometry.py")
        self.assertEqual(len(examples), 2,
                         "the page used to show this module twice, in "
                         "section 5 and section 7")
        rectangles = {self.quoted_rectangle(example)
                      for example in examples}
        self.assertEqual(len(rectangles), 1,
                         "the two blocks quote different rectangles: "
                         "%s" % sorted(rectangles))
        proc = self.shell(examples[0].command)
        self.assertEqual(proc.stdout.split()[-1], rectangles.pop())

    @unittest.skipUnless(shutil.which("tesseract"),
                         "tesseract is not installed on this host")
    def test_the_clock_reader_reads_the_capture_it_quotes(self):
        example, proc = self.run_documented("ocr_clock.py")
        self.assertEqual(proc.stdout.split(), list(example.output))

    def test_the_resume_probe_reports_the_save_that_is_here(self):
        # The page shows this twice -- annotated in section 5 and bare
        # in the resume-versus-create section -- and the two have to be
        # the same invocation, or one of them is stale.
        examples = self.all_documented("session.py probe")
        self.assertEqual(len(examples), 2,
                         "the page used to show the probe twice, at "
                         "README lines %s"
                         % [example.line for example in examples])
        commands = {without_note(example.command)
                    for example in examples}
        self.assertEqual(len(commands), 1,
                         "the page writes this probe two ways: %s"
                         % sorted(commands))
        proc = self.shell(commands.pop())
        reported = dict(line.split("=", 1)
                        for line in proc.stdout.splitlines()
                        if "=" in line)
        # WHAT IS HERE IS NO LIVE CHARACTER, AND THE PROBE SAYS SO.  The
        # survivor died and the engine's own cleanup_at_end() ran to
        # completion, so move_save_to_graveyard() relocated her save into
        # userdir/graveyard/ and the world was cleared -- WORLD_END sits
        # at the engine default `reset` and she was its only character.
        # So the answer is `create`, and it is asserted against the tree
        # rather than against a remembered one: no character save exists
        # under userdir/save, and the probe counts none.
        characters = glob.glob(os.path.join(
            PLAYTHROUGH, "userdir", "save", "*", "#*.sav"))
        self.assertEqual(characters, [],
                         "a character save is here, so the probe's "
                         "answer should not be 'create'")
        self.assertEqual(reported.get("PLAYTHROUGH_SESSION_MODE"),
                         "create")
        self.assertEqual(reported.get("PLAYTHROUGH_SAVE_CHAR_COUNT"), "0")
        self.assertEqual(
            reported.get("PLAYTHROUGH_SAVE_RESUMABLE_COUNT"), "0")

    def test_the_audit_reports_no_debug_binding(self):
        example, proc = self.run_documented("session.py audit")
        self.assertIn("DEBUG_BINDINGS=none", proc.stdout.splitlines())

    def test_the_status_counter_agrees_with_the_captures(self):
        example, proc = self.run_documented("session.py status")
        reported = dict(
            line.split("=", 1) for line in proc.stdout.splitlines()
            if "=" in line)
        captures = len(glob.glob(os.path.join(
            PLAYTHROUGH, "frames", "frame_*.png")))
        with open(os.path.join(PLAYTHROUGH, "manifest.jsonl"),
                  encoding="utf-8") as handle:
            rows = sum(1 for line in handle if line.strip())
        self.assertEqual(int(reported["FRAME_LAST"]), captures)
        self.assertEqual(captures, rows)

    def test_the_committer_status_reads_and_writes_nothing(self):
        example, proc = self.run_documented(
            "commit_artifacts.sh status")
        reported = dict(
            line.split("=", 1) for line in proc.stdout.splitlines()
            if "=" in line)
        self.assertEqual(reported["CHECKPOINT"], "status")
        self.assertEqual(reported["FRAMES"], reported["ROWS"])

    def test_the_environment_report_names_the_contract_it_quotes(self):
        example = self.documented_exactly(
            "bash playthrough/tooling/env.sh")
        quoted = {}
        for line in example.output:
            fields = line.split()
            if len(fields) == 2 and fields[0] in CONTRACT_KEYS:
                quoted[fields[0]] = fields[1]
        self.assertEqual(sorted(quoted), sorted(CONTRACT_KEYS),
                         "the quotation no longer shows every contract "
                         "value this test holds it to")
        proc = self.shell(example.command)
        reported = {}
        for line in proc.stdout.splitlines():
            fields = line.split()
            if len(fields) == 2:
                reported[fields[0]] = fields[1]
        for key, value in sorted(quoted.items()):
            with self.subTest(key=key):
                self.assertEqual(reported.get(key), value)
        self.assertNotEqual(reported.get("SDL_VIDEODRIVER"), "dummy")

    def test_the_report_answers_the_interpreter_query_it_quotes(self):
        example, proc = self.run_documented("grep PLAYTHROUGH_PYTHON")
        keys = [line.split()[0] for line in example.output]
        self.assertEqual(keys, ["PLAYTHROUGH_PYTHON",
                                "PLAYTHROUGH_PYTHON_VERSION",
                                "PLAYTHROUGH_PYTHON_ABI"])
        reported = {}
        for line in proc.stdout.splitlines():
            fields = line.split()
            if len(fields) == 2:
                reported[fields[0]] = fields[1]
        self.assertEqual(sorted(reported), sorted(keys))
        # The path and patch version are this host's; the ABI is the
        # one the pins contract for, so that one is held exactly.
        quoted = dict(line.split() for line in example.output)
        self.assertEqual(reported["PLAYTHROUGH_PYTHON_ABI"],
                         quoted["PLAYTHROUGH_PYTHON_ABI"])

    def test_the_report_answers_the_platform_query_it_quotes(self):
        example, proc = self.run_documented("PLATFORM|TRUST")
        for line in example.output:
            key = line.split()[0]
            with self.subTest(key=key):
                self.assertIn(key, proc.stdout)
        # Values here are facts about the host, so only the keys are
        # asserted -- except that a bare run declares no bypass.
        self.assertIn("PLAYTHROUGH_TRUST_BYPASSES <none>",
                      collapse(proc.stdout))


class TestTheLintClaimsHold(ExampleFixture):
    """The page's own account of how the lint gate must be measured."""

    @unittest.skipUnless(shutil.which("flake8"),
                         "flake8 is not installed on this host")
    def test_the_new_tree_is_clean_exactly_as_it_claims(self):
        example, proc = self.run_documented("flake8 playthrough/")
        self.assertEqual(proc.stdout.splitlines(),
                         list(example.output))

    @unittest.skipUnless(shutil.which("flake8"),
                         "flake8 is not installed on this host")
    def test_the_global_run_still_fails_only_where_it_says(self):
        example, proc = self.run_documented("flake8; echo")
        lines = proc.stdout.splitlines()
        self.assertEqual(lines[-1], "exit=1")
        for quotation in example.output[:-1]:
            prefix = quotation.split("\u2026")[0].rstrip()
            with self.subTest(finding=prefix):
                self.assertIn(prefix, proc.stdout)
        for line in lines[:-1]:
            with self.subTest(line=line):
                self.assertNotIn("playthrough/", line)
        self.assertEqual(len(lines) - 1, len(example.output) - 1,
                         "the global run now reports %d findings; the "
                         "page quotes %d"
                         % (len(lines) - 1, len(example.output) - 1))


class TestThisSuiteTouchesNothing(unittest.TestCase):
    """Read-only by construction, and held to it by its own source."""

    def source(self):
        with open(os.path.abspath(__file__), encoding="utf-8") as file:
            return file.read()

    def test_this_module_opens_no_file_for_writing(self):
        for node in ast.walk(ast.parse(self.source())):
            if not isinstance(node, ast.Call):
                continue
            name = ast.unparse(node.func)
            if name not in ("open", "io.open"):
                continue
            modes = [ast.unparse(argument) for argument
                     in node.args[1:]]
            modes += [ast.unparse(keyword.value) for keyword
                      in node.keywords if keyword.arg == "mode"]
            for mode in modes:
                with self.subTest(mode=mode):
                    for letter in ("w", "a", "x", "+"):
                        self.assertNotIn(letter, mode)

    def test_this_module_calls_no_writing_helper(self):
        forbidden = ("shutil.copy", "shutil.copy2", "shutil.copytree",
                     "shutil.move", "shutil.rmtree", "os.remove",
                     "os.unlink", "os.rmdir", "os.makedirs",
                     "os.mkdir", "os.rename", "os.replace",
                     "os.truncate", "tempfile.mkstemp",
                     "tempfile.mkdtemp")
        calls = set()
        for node in ast.walk(ast.parse(self.source())):
            if isinstance(node, ast.Call):
                calls.add(ast.unparse(node.func))
        for name in sorted(forbidden):
            with self.subTest(call=name):
                self.assertNotIn(name, calls)

    def test_this_module_runs_no_git_command_that_writes(self):
        # The verbs are written in SINGLE quotes so that the token this
        # test searches for -- the verb in DOUBLE quotes, as a git
        # argument would be written here -- does not appear in this
        # file merely because this test names it.  `assertTrue` rather
        # than `assertNotIn` keeps the whole module out of the failure
        # message.
        source = self.source()
        for verb in ('add', 'commit', 'checkout', 'reset', 'clean',
                     'push', 'config'):
            token = '"%s"' % verb
            with self.subTest(verb=verb):
                self.assertTrue(token not in source,
                                "this module names the writing git "
                                "argument %s; it must only read"
                                % token)

    def test_no_bytecode_sits_beside_these_modules(self):
        self.assertFalse(
            os.path.isdir(os.path.join(TOOLING, "__pycache__")),
            "playthrough/tooling/__pycache__ exists; the terminal "
            "!/playthrough/** negation would commit it, which is why "
            "every documented Python command carries -B")


if __name__ == "__main__":
    unittest.main(verbosity=2)
