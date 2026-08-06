#!/usr/bin/env python3
"""Regression suite for playthrough/tooling/launch_game.sh.

Three of this script's decisions are hard requirements of the project,
and every one of them can regress without anything crashing:

* THE BUILD ARGUMENTS.  `SDL3=0` is mandatory on every make invocation,
  because the Makefile defaults SDL3=1 whenever TILES=1 and then raises
  a hard error when pkg-config cannot satisfy SDL3 >= 3.4.0.  `TESTS=0`
  must never be passed.  Parallelism is capped by MEMORY, not CPU count:
  a wider build is OOM-killed and reports "Killed" rather than a compile
  error.
* THE TILES PROOF.  The SDL tiles binary is played and the curses build
  is never an acceptable substitute, and the binary settles it from its
  own mouth -- "+tiles" in its --version output.  Nothing else is
  trusted: not the file name, not the presence of gfx/.
* RESUME VERSUS CREATE.  If a save already exists it MUST be continued.
  A world is written the moment it is created, so a run interrupted
  during character creation leaves a world with no character save; that
  world is not resumable and must not be mistaken for one.  Two
  resumable worlds is ambiguous and is refused rather than guessed,
  because directory order is locale- and filesystem-dependent.

    python3 playthrough/tooling/test_launch_game.py
    python3 -B -m unittest discover -s playthrough/tooling -p 'test_*.py'

HOW A LAUNCHER IS TESTED WITHOUT BUILDING OR LAUNCHING ANYTHING
Two harnesses, both running the REAL script inside a temporary SANDBOX
CHECKOUT (data/, gfx/, lang/, Makefile, src/path_info.cpp and copies of
env.sh and launch_game.sh), started with `env -i` and a PATH holding
only a purpose-built tool directory:

* SUBCOMMAND RUNS execute the script as an ordinary command, with
  recording stubs for make, the compiler, xdpyinfo, xprop and xdotool.
  The make stub records its exact argv and creates a stub binary, which
  is what a real make does, so the whole build path -- preflight,
  compiler check, detached spawn, status sentinel, tiles assertion --
  runs in about a second.
* SOURCED RUNS source the script with the `help` subcommand, which is
  answered before anything is validated and leaves every function
  defined.  A single function can then be called with the globals a test
  chooses, which is how check_capture_geometry's strict and warn modes,
  the tunable validators and the clamp are exercised directly.

Standard library only.  Nothing outside the temporary directory is
written, no build is run, no game is launched, and no real X server is
touched.
"""

import atexit
import hashlib
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest

# Keep bytecode out of playthrough/tooling/: the terminal
# `!/playthrough/**` negation in .gitignore re-includes anything
# written there.
sys.dont_write_bytecode = True

TOOLING = os.path.dirname(os.path.abspath(__file__))
PLAYTHROUGH = os.path.dirname(TOOLING)
REPO_ROOT = os.path.dirname(PLAYTHROUGH)


def _is_private(path):
    """True when PATH and every directory above it are trustworthy.

    The same rule env.sh's playthrough_verify_executable and
    launch_game.sh's verify_pack_provenance apply: every component is
    owned by root or by this user and none of them is group- or
    world-writable, so nobody else can substitute a file between a check
    and the run that follows it.
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

    THE SANDBOX HAS TO BE TRUSTWORTHY, because launch_game.sh now
    refuses to start or accept an instance that will be captured while
    any of env.sh's trust bypasses is set.  A suite that declared those
    bypasses would exercise only the relaxed path and would assert
    nothing about the enforced one.

    /tmp cannot be the base: this host has it at mode 2777 --
    world-writable with no sticky bit -- so the ancestor walk fails
    there however the sandbox itself is built.  $HOME serves on an
    ordinary host and /run on a root one, and $PLAYTHROUGH_TEST_TMPDIR
    overrides both.  With none available the suite skips, naming that
    variable, rather than quietly testing something weaker.
    """
    candidates = []
    nominated = os.environ.get("PLAYTHROUGH_TEST_TMPDIR")
    if nominated:
        candidates.append(nominated)
    home = os.environ.get("HOME")
    if home:
        candidates.append(
            os.path.join(home, ".cache", "playthrough-tooling-tests"))
    if os.geteuid() == 0:
        candidates.append("/run/playthrough-tooling-tests")
    for candidate in candidates:
        try:
            os.makedirs(candidate, mode=0o700, exist_ok=True)
        except OSError:
            continue
        if _is_private(candidate):
            return candidate
    return None


SANDBOX_BASE = _sandbox_base()
NO_SANDBOX_BASE = (
    "no private directory is available for the sandbox: set "
    "PLAYTHROUGH_TEST_TMPDIR to one that only root or this user can "
    "write, with no group- or world-writable directory above it")

# The documented exit codes, named as launch_game.sh names them.
EX_OK = 0
EX_USAGE = 1
EX_LAYOUT = 2
EX_BUILD = 3
EX_NOT_TILES = 4
EX_DISPLAY = 5
EX_TILESET = 6
EX_WINDOW = 7
EX_PREREQ = 8

# The one sanctioned build command, argument by argument.
REQUIRED_MAKE_ARGS = (
    "RELEASE=1", "TILES=1", "SOUND=1", "SDL3=0", "ASTYLE=0",
    "LINTJSON=0", "CCACHE=1",
)
FORBIDDEN_MAKE_ARGS = ("TESTS=0", "NATIVE=linux64", "SDL3=1")

VERSION_LINE = "Cataclysm Dark Days Ahead: f38c2fbae3 +tiles, +sound"
CURSES_LINE = "Cataclysm Dark Days Ahead: f38c2fbae3"

# The first pid read a launch does NOT need: the pre-launch
# idempotency probe reads one and the window wait reads the one that
# accepts the window, so poisoning the third proves that no step after
# the acceptance re-derives what was already verified.
READ_GAME_PID_CALL = 3

# The display env.sh derives with no CLONE_INDEX set.  The identity
# check compares a candidate process's DISPLAY against it, so the
# fixture has to spawn its impostors onto the same one.
DISPLAY = ":99"

MSX_ID = "MshockXottoplus"
MSX_VIEW = "MSXotto+"
ASCII_ID = "ASCIITiles"

# The coreutils the script really runs.  Nothing else is on PATH.
REAL_TOOLS = (
    "bash", "date", "awk", "grep", "mkdir", "mv", "rm", "wc", "tail",
    "head", "dirname", "basename", "cat", "env", "chmod", "cp", "ls",
    "tr", "sed", "sort", "readlink", "touch", "sleep", "setsid",
    "nohup", "kill", "pwd", "cut", "stat", "timeout", "id",
    "flock", "realpath", "find", "sha256sum", "mktemp",
)

# A GENUINE PROCESS IS REQUIRED TO TEST THE LIVE-INSTANCE PATH, and a
# shell script cannot be one.  pid_is_our_game resolves
# /proc/<pid>/exe and compares it with the game binary, and for a
# script that link resolves to the INTERPRETER -- so a scripted stub is
# correctly judged not to be the game, and every branch downstream of
# pid confirmation becomes unreachable.  This is a real ELF: its own
# /proc/<pid>/exe is the path it was started from, it runs from the
# checkout, and its argv carries --userdir, which is exactly the
# three-fact identity the script insists on.
FAKE_GAME_SOURCE = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

static void write_pidfile(const char *path)
{
    FILE *handle = fopen(path, "w");
    if (handle == NULL) {
        return;
    }
    fprintf(handle, "%ld\n", (long)getpid());
    fclose(handle);
}

static void write_options(const char *path)
{
    char parent[4096];
    char *cut;
    FILE *handle;

    if (strlen(path) >= sizeof(parent)) {
        return;
    }
    strcpy(parent, path);
    cut = strrchr(parent, '/');
    if (cut != NULL) {
        *cut = '\0';
        mkdir(parent, 0755);
    }
    handle = fopen(path, "w");
    if (handle == NULL) {
        return;
    }
    fprintf(handle, "[]\n");
    fclose(handle);
}

int main(int argc, char **argv)
{
    const char *version = getenv("FAKE_GAME_VERSION");
    const char *pidfile = getenv("FAKE_GAME_PIDFILE");
    const char *options = getenv("FAKE_GAME_OPTIONS");
    const char *lifetime = getenv("FAKE_GAME_LIFETIME");
    int seconds = 30;
    int i;

    for (i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--version") == 0) {
            printf("%s\n", version == NULL ? "" : version);
            return 0;
        }
    }
    if (pidfile != NULL && pidfile[0] != '\0') {
        write_pidfile(pidfile);
    }
    printf("fake engine up as pid %ld\n", (long)getpid());
    fflush(stdout);
    if (options != NULL && options[0] != '\0') {
        write_options(options);
    }
    if (lifetime != NULL && lifetime[0] != '\0') {
        seconds = atoi(lifetime);
    }
    if (seconds > 0) {
        sleep((unsigned int)seconds);
    }
    return 0;
}
"""

_FAKE_GAME = {"path": None, "why": None}


def fake_game_binary():
    """Compile the fake engine once, and reuse it for every test."""
    if _FAKE_GAME["path"] is not None or _FAKE_GAME["why"] is not None:
        return _FAKE_GAME["path"]
    compiler = shutil.which("cc") or shutil.which("gcc")
    if compiler is None:
        _FAKE_GAME["why"] = "no C compiler on PATH"
        return None
    holder = tempfile.mkdtemp(prefix="blitzy_fakegame_",
                              dir=SANDBOX_BASE)
    atexit.register(shutil.rmtree, holder, True)
    source = os.path.join(holder, "fake_game.c")
    binary = os.path.join(holder, "fake_game")
    with open(source, "w", encoding="utf-8") as handle:
        handle.write(FAKE_GAME_SOURCE)
    built = subprocess.run(
        [compiler, "-O0", "-o", binary, source],
        capture_output=True, timeout=300)
    if built.returncode != 0 or not os.path.isfile(binary):
        shutil.rmtree(holder, True)
        _FAKE_GAME["why"] = "the fake engine did not compile"
        return None
    _FAKE_GAME["path"] = binary
    return binary


class LaunchFixture(unittest.TestCase):
    """A sandbox checkout with a stubbed build and display toolchain."""

    def setUp(self):
        if SANDBOX_BASE is None:
            self.skipTest(NO_SANDBOX_BASE)
        self.root = tempfile.mkdtemp(prefix="blitzy_launch_",
                                     dir=SANDBOX_BASE)
        self.addCleanup(shutil.rmtree, self.root, True)
        self.checkout = os.path.join(self.root, "checkout")
        self.tooling = os.path.join(self.checkout, "playthrough",
                                    "tooling")
        os.makedirs(self.tooling)
        for name in ("data", "gfx", "lang"):
            os.makedirs(os.path.join(self.checkout, name))
        os.makedirs(os.path.join(self.checkout, "src"))
        self.write(os.path.join(self.checkout, "src", "path_info.cpp"),
                   "// a marker, not the engine\n")
        self.write(os.path.join(self.checkout, "Makefile"),
                   "# a marker, not the build system\n")
        for name in ("env.sh", "launch_game.sh"):
            shutil.copyfile(os.path.join(TOOLING, name),
                            os.path.join(self.tooling, name))
        os.chmod(os.path.join(self.tooling, "launch_game.sh"), 0o755)
        self.script = os.path.join(self.tooling, "launch_game.sh")
        self.game = os.path.join(self.checkout, "cataclysm-tiles")
        self.saves = os.path.join(self.checkout, "playthrough",
                                  "userdir", "save")
        self.config = os.path.join(self.checkout, "playthrough",
                                   "userdir", "config")
        self.stub_log = os.path.join(self.root, "stub.log")
        # A pack directory that does NOT exist unless a test creates
        # one.  The default is the host's /opt/cdda-gfx-cache, which is
        # populated on this machine; pointing it inside the sandbox is
        # what keeps every tileset outcome decided by the fixture.
        self.pack = os.path.join(self.root, "pack")
        self.bin = os.path.join(self.root, "bin")
        os.makedirs(self.bin)
        # The fake engine's own record of its pid, which the xdotool
        # stub reports as the window's _NET_WM_PID.
        self.game_pidfile = os.path.join(self.root, "fake_game.pid")
        # Where env.sh is told to keep this run's scratch state.  Every
        # log and pid file lands inside it, verified mode 0700.
        self.scratch = os.path.join(self.root, "runtime")
        self.link_real_tools()
        self.write_stubs()
        # PLAYTHROUGH_GAME_LOG is host-global and env.sh exports it
        # unconditionally, so a run of this suite would leave it behind
        # on a host that had none.  Remove only what this suite made.
        self.host_log = "/tmp/cata-play.log"
        self.host_log_existed = os.path.exists(self.host_log)
        self.addCleanup(self.forget_host_log)

    def forget_host_log(self):
        """Delete the host-global game log only if we created it."""
        if self.host_log_existed:
            return
        if os.path.exists(self.host_log):
            os.unlink(self.host_log)

    # -- fixture plumbing --------------------------------------------

    def write(self, path, text, mode=None):
        """Write a file, creating its parent, and return the path.

        AN EXISTING SYMLINK IS REPLACED, NEVER WRITTEN THROUGH.  This
        fixture puts symlinks to real system tools on a private PATH and
        then overrides some of them with stubs; opening such a name for
        writing would follow the link and truncate the HOST's binary.
        Removing the link first keeps every write inside the sandbox.
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
        """Symlink the genuine coreutils the script needs."""
        for tool in REAL_TOOLS:
            resolved = shutil.which(tool)
            link = os.path.join(self.bin, tool)
            if resolved and not os.path.exists(link):
                os.symlink(resolved, link)

    def stub(self, name, body):
        """Install a recording stub for one external command."""
        path = self.write(
            os.path.join(self.bin, name),
            "#!/bin/bash\n"
            'printf "%s\\t%s\\n" "' + name + '" "$*"'
            ' >>"${PLAYTHROUGH_STUB_LOG}"\n' + body,
            mode=0o755)
        self.assert_inside_sandbox(path)
        return path

    def assert_inside_sandbox(self, path):
        """Refuse to have written anything outside the sandbox."""
        resolved = os.path.realpath(path)
        if not resolved.startswith(os.path.realpath(self.root)):
            raise AssertionError(
                "%s resolved to %s, outside the sandbox: a stub must "
                "never be written through a symlink to a host tool"
                % (path, resolved))

    def write_stubs(self):
        """The build, display and window tools, stubbed."""
        # make records its argv AND the compiler it was handed, then
        # does what a real make does: it produces the binary.  Without
        # that, the tiles assertion after the build would have nothing
        # to assert against.  CXX arrives through the ENVIRONMENT --
        # `env "CXX=..." make ...` -- so recording argv alone would
        # miss it entirely.
        self.stub("make", (
            'printf "make-env\\tCXX=%s\\n" "${CXX-unset}"'
            ' >>"${PLAYTHROUGH_STUB_LOG}"\n'
            'if [ "${STUB_MAKE_BUILDS:-1}" = "1" ]; then\n'
            '    printf "#!/bin/bash\\nprintf \'%%s\\\\n\''
            ' \\"${STUB_VERSION:-' + VERSION_LINE + '}\\"\\n"'
            ' >"${PLAYTHROUGH_GAME_BIN}"\n'
            '    chmod 755 "${PLAYTHROUGH_GAME_BIN}"\n'
            "fi\n"
            'exit "${STUB_MAKE_RC:-0}"\n'))
        self.stub("ccache", "exit 0\n")
        self.stub("g++-14", (
            'case "$*" in\n'
            "    *-dumpversion*)\n"
            '        printf "%s\\n" "${STUB_COMPILER_VERSION-14.3.0}"\n'
            "        ;;\n"
            "esac\n"
            "exit 0\n"))
        self.stub("g++-15", (
            'case "$*" in\n'
            "    *-dumpversion*) printf \"15.2.0\\n\" ;;\n"
            "esac\n"
            "exit 0\n"))
        # A COOKIELESS CLIENT IS REFUSED, as a real authenticated
        # server refuses one: env.sh proves access control NEGATIVELY,
        # by requiring xdpyinfo with an empty authority file to FAIL.
        # STUB_XDPYINFO_OPEN=1 answers anyway, for the test that asserts
        # the refusal of an open display.
        self.stub("xdpyinfo", (
            'if [ "${STUB_XDPYINFO_OPEN:-0}" != "1" ]; then\n'
            '    case "${XAUTHORITY:-}" in\n'
            '        ""|/dev/null) exit 1 ;;\n'
            "    esac\n"
            "fi\n"
            'if [ "${STUB_XDPYINFO_RC:-0}" != "0" ]; then\n'
            '    exit "${STUB_XDPYINFO_RC}"\n'
            "fi\n"
            'printf "dimensions:    %s pixels\\n"'
            ' "${STUB_DIMENSIONS:-1920x1080}"\n'
            'printf "depth of root window:    %s planes\\n"'
            ' "${STUB_DEPTH:-24}"\n'))
        self.stub("xprop", (
            'printf "_NET_SUPPORTING_WM_CHECK(WINDOW): window id #'
            ' 0x400001\\n"\n'))
        # getwindowpid answers with the pid the fake engine recorded,
        # which is how a real window's _NET_WM_PID behaves.  It waits
        # briefly, because the engine records its pid as its first act
        # and the search that finds the window is stubbed to succeed
        # immediately.
        self.stub("xdotool", (
            'case "$1" in\n'
            "    search)\n"
            # A window that is there and then is not: the class search
            # reports nothing from the Nth call onward, which is how
            # the liveness re-check sees a window disappear underneath
            # a process that is still running.
            '        if [ -n "${STUB_SEARCH_EMPTY_FROM-}" ]; then\n'
            '            _seen="$(cat "${STUB_SEARCH_COUNTER}"'
            " 2>/dev/null || printf 0)\"\n"
            "            _seen=$(( _seen + 1 ))\n"
            '            printf "%s" "${_seen}"'
            ' >"${STUB_SEARCH_COUNTER}"\n'
            '            if [ "${_seen}" -ge'
            ' "${STUB_SEARCH_EMPTY_FROM}" ]; then\n'
            "                exit 1\n"
            "            fi\n"
            "        fi\n"
            '        if [ -z "${STUB_WINDOW_IDS-}" ]; then\n'
            "            exit 1\n"
            "        fi\n"
            '        printf "%s\\n" ${STUB_WINDOW_IDS}\n'
            "        ;;\n"
            "    getwindowgeometry)\n"
            '        printf "WINDOW=%s\\nX=0\\nY=4\\nWIDTH=%s\\n'
            'HEIGHT=%s\\n" "$3" "${STUB_WINDOW_WIDTH:-1920}"'
            ' "${STUB_WINDOW_HEIGHT:-1072}"\n'
            "        ;;\n"
            "    getwindowpid)\n"
            '        if [ -n "${STUB_WINDOW_PID_FAIL-}" ]; then\n'
            "            exit 1\n"
            "        fi\n"
            # Simulate the race the launcher defends against: the pid
            # is readable when the window is found and unreadable a
            # moment later, when it is asked for again.  Which call
            # that is has to be selected by ordinal, because the
            # window search runs in a subshell and its own log line can
            # land either side of the read it precedes.
            '        if [ -n "${STUB_WINDOW_PID_FAIL_NTH-}" ]; then\n'
            '            _seen="$(cat "${STUB_WINDOW_PID_COUNTER}"'
            " 2>/dev/null || printf 0)\"\n"
            "            _seen=$(( _seen + 1 ))\n"
            '            printf "%s" "${_seen}"'
            ' >"${STUB_WINDOW_PID_COUNTER}"\n'
            '            if [ "${_seen}" -eq'
            ' "${STUB_WINDOW_PID_FAIL_NTH}" ]; then\n'
            "                exit 1\n"
            "            fi\n"
            "        fi\n"
            '        if [ -n "${STUB_WINDOW_PIDS-}" ]; then\n'
            "            for _pair in ${STUB_WINDOW_PIDS}; do\n"
            '                case "${_pair}" in\n'
            '                    "$2":*)\n'
            '                        printf "%s\\n" "${_pair#*:}"\n'
            "                        exit 0\n"
            "                        ;;\n"
            "                esac\n"
            "            done\n"
            "            exit 1\n"
            "        fi\n"
            '        if [ -n "${STUB_WINDOW_PID-}" ]; then\n'
            '            printf "%s\\n" "${STUB_WINDOW_PID}"\n'
            "            exit 0\n"
            "        fi\n"
            "        _waited=0\n"
            '        while [ "${_waited}" -lt 10 ]; do\n'
            '            if [ -s "${FAKE_GAME_PIDFILE-/nonexistent}" ]'
            "; then\n"
            '                cat "${FAKE_GAME_PIDFILE}"\n'
            "                exit 0\n"
            "            fi\n"
            "            sleep 0.05\n"
            "            _waited=$(( _waited + 1 ))\n"
            "        done\n"
            "        exit 1\n"
            "        ;;\n"
            "esac\n"
            "exit 0\n"))
        self.stub("Xvfb", "exit 0\n")
        self.stub("openbox", "exit 0\n")
        # setsid normally EXECS, so the spawn pid the launcher records
        # happens to be the game's.  The script's own comments note
        # that setsid MAY FORK, in which case the recorded pid is
        # setsid's and not the game's -- which is why the window's
        # _NET_WM_PID is the authoritative source and the spawn pid
        # only a fallback.  This stub can reproduce the forking form on
        # demand so that the fallback's failure is reachable.
        real_setsid = shutil.which("setsid") or "/usr/bin/setsid"
        self.stub("setsid", (
            'if [ -n "${STUB_SETSID_FORKS-}" ]; then\n'
            '    "$@" &\n'
            '    wait "$!"\n'
            "    exit \"$?\"\n"
            "fi\n"
            'exec "' + real_setsid + '" "$@"\n'))

    def install_game(self, version=VERSION_LINE):
        """Put a scripted game stub at the checkout root.

        It answers --version, and when launched it writes the options
        file the way the engine does on first run, so the calibration
        path does not have to wait out its own 60s timeout.  What it
        cannot do is be a confirmable game process; see
        install_live_game.
        """
        return self.write(
            self.game,
            "#!/bin/bash\n"
            'case "$*" in\n'
            "    *--version*)\n"
            "        printf '%s\\n' \"" + version + "\"\n"
            "        exit 0\n"
            "        ;;\n"
            "esac\n"
            # CREATES the options file, never clobbers a seeded one:
            # the engine writes it on first run, and a stub that
            # truncated an existing one would erase the very values the
            # capture launch is about to verify.
            'if [ -n "${PLAYTHROUGH_OPTIONS_JSON-}" ] &&\n'
            '   [ ! -f "${PLAYTHROUGH_OPTIONS_JSON}" ]; then\n'
            '    mkdir -p "$(dirname "${PLAYTHROUGH_OPTIONS_JSON}")"\n'
            '    printf "[]\\n" >"${PLAYTHROUGH_OPTIONS_JSON}"\n'
            "fi\n"
            "exit 0\n",
            mode=0o755)

    def install_live_game(self):
        """Put the compiled fake engine at the checkout root."""
        binary = fake_game_binary()
        if binary is None:
            self.skipTest(_FAKE_GAME["why"])
        shutil.copyfile(binary, self.game)
        os.chmod(self.game, 0o755)
        self.addCleanup(self.stop_live_game)
        return self.game

    def stop_live_game(self):
        """Signal the exact pid the fake engine recorded, if any.

        Only a numeric pid this fixture's own child wrote is ever
        signalled: no pattern, no name match, nothing that could reach
        another process on this host.
        """
        if not os.path.isfile(self.game_pidfile):
            return
        with open(self.game_pidfile, encoding="utf-8") as handle:
            raw = handle.read().strip()
        if not raw.isdigit():
            return
        pid = int(raw)
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            return
        # Wait for it to actually go, so nothing is still running out
        # of the sandbox when the sandbox is removed.
        deadline = time.time() + 10.0
        while time.time() < deadline:
            if not os.path.exists("/proc/%d" % pid):
                return
            time.sleep(0.02)

    def await_exec_of(self, pid, binary, timeout=10.0):
        """Wait until that pid really is running that binary.

        Between fork and exec, /proc/<pid>/exe still resolves to the
        spawning interpreter, and the script's identity check would
        correctly refuse it -- so the wait is for the exec, not for a
        guessed number of milliseconds.
        """
        wanted = os.path.realpath(binary)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if os.path.realpath("/proc/%d/exe" % pid) == wanted:
                    return True
            except OSError:
                pass
            time.sleep(0.02)
        self.fail("pid %d never became %s" % (pid, wanted))

    def await_exec(self, pid, timeout=10.0):
        """Wait until that pid really is this sandbox's game."""
        return self.await_exec_of(pid, self.game, timeout)

    def live_pid(self, timeout=10.0):
        """The fake engine's pid, once it has recorded one."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if os.path.isfile(self.game_pidfile):
                with open(self.game_pidfile, encoding="utf-8") as fh:
                    raw = fh.read().strip()
                if raw.isdigit():
                    return int(raw)
            time.sleep(0.05)
        return None

    def install_tileset(self, directory, ident, view=None):
        """Write one gfx/<pack>/tileset.txt."""
        conf = os.path.join(self.checkout, "gfx", directory,
                            "tileset.txt")
        lines = ["# a comment, as the shipped packs have",
                 "NAME: %s" % ident]
        if view is not None:
            lines.append("VIEW: %s" % view)
        return self.write(conf, "\n".join(lines) + "\n")

    def install_seeder(self):
        """Put the REAL seed_options.py in the sandbox.

        The launcher delegates the option contract to it before every
        capture launch, and these tests exercise that handoff for real
        rather than through a stub's opinion of it -- the suite's
        interpreter is the host's python3, so the module that owns the
        contract is the module that answers.
        """
        seeder = os.path.join(self.tooling, "seed_options.py")
        if not os.path.isfile(seeder):
            shutil.copyfile(
                os.path.join(TOOLING, "seed_options.py"), seeder)
        # seed_options.py proves it is inside a checkout before it reads
        # anything, and data/json/ui is half of that proof (the other
        # half, src/path_info.cpp, setUp already writes).
        os.makedirs(os.path.join(self.checkout, "data", "json", "ui"),
                    exist_ok=True)
        return seeder

    def seed_config(self, **overrides):
        """An options file that HOLDS the seeded contract.

        A sandbox whose options file merely EXISTS is no longer enough,
        which is the whole point of the launcher's verification: these
        are the eight values it checks, and an override makes exactly one
        of them wrong.
        """
        self.install_seeder()
        values = {
            "24_HOUR": "24h",
            "SOUND_ENABLED": "false",
            "USE_TILES": "true",
            "TILES": MSX_ID,
            "TERMINAL_X": "240",
            "TERMINAL_Y": "67",
            "CHARACTER_POINT_POOLS": "any",
            "WORLD_COMPRESSION2": "false",
            "FONT_WIDTH": "8",
            "FONT_HEIGHT": "16",
            "SIDEBAR_POSITION": "right",
        }
        values.update(overrides)
        entries = [{"info": "what %s does" % name, "default": value,
                    "name": name, "value": value}
                   for name, value in values.items()]
        return self.write(os.path.join(self.config, "options.json"),
                          json.dumps(entries, indent=2) + "\n")

    def install_pack(self, directory, ident, view=None, manifest=True):
        """Write one pre-placed pack entry outside the checkout.

        WITH A REAL sha256 MANIFEST, because the ingestion gate
        verifies one and that verification is exercised here rather
        than switched off.  `manifest=False` produces a pack that is
        deliberately unverifiable, for the tests that assert refusal.
        """
        conf = os.path.join(self.pack, directory, "tileset.txt")
        lines = ["NAME: %s" % ident]
        if view is not None:
            lines.append("VIEW: %s" % view)
        self.write(os.path.join(self.pack, directory, "tile_config.json"),
                   "{}\n")
        written = self.write(conf, "\n".join(lines) + "\n")
        if manifest:
            self.write_pack_manifest(directory)
        return written

    def write_pack_manifest(self, directory, corrupt=False):
        """Write SHA256SUMS over every regular file in one pack entry."""
        holder = os.path.join(self.pack, directory)
        rows = []
        for base, _, names in os.walk(holder):
            for name in sorted(names):
                if name == "SHA256SUMS":
                    continue
                path = os.path.join(base, name)
                with open(path, "rb") as handle:
                    digest = hashlib.sha256(handle.read()).hexdigest()
                if corrupt:
                    digest = "0" * 64
                rows.append("%s  %s" % (
                    digest, os.path.relpath(path, holder)))
        return self.write(os.path.join(holder, "SHA256SUMS"),
                          "\n".join(rows) + "\n")

    def ready_to_launch(self):
        """A sandbox that gets as far as the launch decision.

        `launch` runs the binary check and the tileset resolution
        first, so both have to succeed before the calibration versus
        capture decision is even reached.
        """
        self.install_game()
        self.install_tileset("MShockXotto+", MSX_ID, MSX_VIEW)

    def install_world(self, name, characters=(), master=True):
        """Write one save/<World>/ with the character files given."""
        holder = os.path.join(self.saves, name)
        os.makedirs(holder, exist_ok=True)
        if master:
            self.write(os.path.join(holder, "master.gsav"), "{}\n")
        for character in characters:
            self.write(os.path.join(holder, character), "save\n")
        return holder

    # -- running it --------------------------------------------------

    def environment(self, **overrides):
        """The pristine environment every run starts from."""
        interpreter = shutil.which("python3") or sys.executable
        # The RUNTIME DIRECTORY is pointed into the sandbox rather
        # than the scratch paths being pointed out of it.  env.sh
        # confines every log and pid file to PLAYTHROUGH_RUNTIME_DIR --
        # a mode-0700 directory it creates, owner-checks and refuses to
        # follow a symlink into -- precisely so that a caller cannot
        # redirect a truncating write somewhere else.  Nominating the
        # whole directory is the sanctioned way to relocate it, and the
        # nominated one is verified exactly as the default is.
        scratch = self.scratch
        os.makedirs(scratch, exist_ok=True)
        os.chmod(scratch, 0o700)
        env = {
            "PATH": self.bin,
            "HOME": self.root,
            "PLAYTHROUGH_RUNTIME_DIR": scratch,
            # NO TRUST BYPASS IS DECLARED HERE, DELIBERATELY.
            #
            # launch_game.sh refuses to start or accept an instance that
            # will be captured while any of them is set, so a fixture
            # that declared one would only ever exercise the diagnostic
            # path.  The sandbox is instead built to PASS the real
            # checks: it lives under a private base (see
            # _sandbox_base), so the stubs, the fake engine and the
            # staged pack all verify, and the xdpyinfo stub refuses a
            # cookieless client exactly as an authenticated server does.
            # Each refusal keeps its own test, which arranges the
            # untrustworthy condition on purpose.
            "PLAYTHROUGH_STUB_LOG": self.stub_log,
            # THE PLATFORM GATE IS SATISFIED, NOT SWITCHED OFF.
            # playthrough_check_platform REFUSES an out-of-support or
            # untabulated release by default, and the host this suite
            # runs on may well be one -- so without a waiver every test
            # here would exercise the prerequisite refusal and assert
            # nothing about the subject.  The waiver takes a REASON,
            # which is what makes declaring it in a fixture honest: it
            # says why, in the same words a run on this host would.  It
            # is not a trust bypass, so the enforced production path is
            # unaffected, and the gate itself has its own tests in
            # test_env.py.
            "PLAYTHROUGH_ALLOW_EOL_PLATFORM":
                "test fixture; the platform gate has its own coverage "
                "in test_env.py",
            "PLAYTHROUGH_PYTHON": interpreter,
            "PLAYTHROUGH_WINDOW_TIMEOUT": "10",
            "PLAYTHROUGH_STOP_TIMEOUT": "10",
            "PLAYTHROUGH_BUILD_TIMEOUT": "60",
            "PLAYTHROUGH_TILESET_PACK": self.pack,
            "PLAYTHROUGH_LIVENESS_SETTLE": "0.2",
            "PLAYTHROUGH_BUILD_LOG": os.path.join(scratch,
                                                  "build.log"),
            "PLAYTHROUGH_GAME_PIDFILE": os.path.join(scratch,
                                                     "game.pid"),
            "FAKE_GAME_PIDFILE": self.game_pidfile,
            "STUB_WINDOW_PID_COUNTER": os.path.join(
                self.root, "getwindowpid.count"),
            "STUB_SEARCH_COUNTER": os.path.join(
                self.root, "search.count"),
            "FAKE_GAME_VERSION": VERSION_LINE,
            "FAKE_GAME_LIFETIME": "30",
        }
        for name, value in overrides.items():
            if value is None:
                env.pop(name, None)
            else:
                env[name] = str(value)
        return env

    def run_launch(self, *args, **overrides):
        """Run launch_game.sh in the sandbox."""
        env = self.environment(**overrides)
        command = ["/usr/bin/env", "-i"]
        command.extend("%s=%s" % item for item in env.items())
        command.extend(["/bin/bash", "--noprofile", "--norc",
                        self.script])
        command.extend(args)
        result = subprocess.run(
            command, cwd=self.checkout, capture_output=True,
            timeout=300)
        return (result.returncode,
                result.stdout.decode("utf-8", "replace"),
                result.stderr.decode("utf-8", "replace"))

    def run_sourced(self, after, **overrides):
        """Source the script, then run ``after`` with its functions.

        ``help`` is answered before anything is validated, so sourcing
        with it leaves every function and constant in place without
        touching the checkout.
        """
        env = self.environment(**overrides)
        program = ('set +e\n. "$1" help >/dev/null\n%s\n' % after)
        command = ["/usr/bin/env", "-i"]
        command.extend("%s=%s" % item for item in env.items())
        command.extend(["/bin/bash", "--noprofile", "--norc", "-c",
                        program, "bash", self.script])
        result = subprocess.run(
            command, cwd=self.checkout, capture_output=True,
            timeout=120)
        return (result.returncode,
                result.stdout.decode("utf-8", "replace"),
                result.stderr.decode("utf-8", "replace"))

    # -- reading the result ------------------------------------------

    def emitted(self, text):
        """Parse the KEY=value channel from stdout."""
        parsed = {}
        for line in text.splitlines():
            if "=" not in line:
                continue
            name, _, value = line.partition("=")
            parsed[name] = value
        return parsed

    def calls(self, name):
        """Every recorded invocation of one stub, as argument text."""
        if not os.path.isfile(self.stub_log):
            return []
        found = []
        with open(self.stub_log, encoding="utf-8") as handle:
            for line in handle:
                tool, _, arguments = line.rstrip("\n").partition("\t")
                if tool == name:
                    found.append(arguments)
        return found


class TestTheSubcommands(LaunchFixture):
    """Exactly one subcommand, and help before any validation."""

    def test_help_lists_every_subcommand(self):
        status, out, _ = self.run_launch("help")
        self.assertEqual(status, EX_OK)
        for name in ("all", "build", "headless", "tileset", "probe",
                     "launch", "guard", "status", "stop", "help"):
            with self.subTest(subcommand=name):
                self.assertIn(name, out)
        self.assertIn("stdout carries KEY=value lines only", out)

    def test_help_answers_even_with_a_broken_tunable(self):
        status, out, _ = self.run_launch(
            "help", PLAYTHROUGH_BUILD_JOBS="lots")
        self.assertEqual(
            status, EX_OK,
            msg=("a malformed tunable must not stop an operator from "
                 "reading the usage that explains what the tunables "
                 "are"))
        self.assertIn("usage:", out)

    def test_an_unknown_subcommand_is_a_usage_error(self):
        status, _, err = self.run_launch("resume-please")
        self.assertEqual(status, EX_USAGE)
        self.assertIn("unknown subcommand", err)

    def test_more_than_one_subcommand_is_refused(self):
        status, _, err = self.run_launch("probe", "launch")
        self.assertEqual(status, EX_USAGE)
        self.assertIn("exactly one subcommand", err)

    def test_a_broken_tunable_stops_every_other_subcommand(self):
        cases = (
            {"PLAYTHROUGH_BUILD_JOBS": "lots"},
            {"PLAYTHROUGH_BUILD_JOBS": "0"},
            {"PLAYTHROUGH_BUILD_JOBS": "-4"},
            {"PLAYTHROUGH_BUILD_TIMEOUT": "1h"},
            {"PLAYTHROUGH_WINDOW_TIMEOUT": "0"},
            {"PLAYTHROUGH_STOP_TIMEOUT": "99999"},
            {"PLAYTHROUGH_LIVENESS_SETTLE": "0"},
            {"PLAYTHROUGH_LIVENESS_SETTLE": "0.0"},
            {"PLAYTHROUGH_LIVENESS_SETTLE": "1.2.3"},
        )
        for overrides in cases:
            with self.subTest(**overrides):
                status, _, err = self.run_launch("probe", **overrides)
                self.assertEqual(status, EX_USAGE)
                self.assertIn("PLAYTHROUGH_", err)

    def test_a_valid_fractional_settle_is_accepted(self):
        status, _, _ = self.run_launch(
            "probe", PLAYTHROUGH_LIVENESS_SETTLE="0.5")
        self.assertEqual(status, EX_OK)

    def test_the_working_directory_must_be_a_checkout(self):
        os.rmdir(os.path.join(self.checkout, "gfx"))
        status, _, err = self.run_launch("probe")
        self.assertEqual(status, EX_LAYOUT)
        self.assertIn("is not the root of a", err)
        self.assertIn("missing gfx", err)


class TestTheBuildCommand(LaunchFixture):
    """One sanctioned build command, and nothing else."""

    def make_argv(self):
        """The recorded make invocation, split into arguments."""
        calls = self.calls("make")
        self.assertEqual(
            len(calls), 1,
            msg="exactly one make invocation: %r" % calls)
        return calls[0].split()

    def test_the_build_passes_every_required_flag(self):
        status, out, err = self.run_launch("build")
        self.assertEqual(status, EX_OK, msg=err)
        argv = self.make_argv()
        for flag in REQUIRED_MAKE_ARGS:
            with self.subTest(flag=flag):
                self.assertIn(flag, argv)

    def test_sdl3_is_disabled_on_every_invocation(self):
        self.run_launch("build")
        self.assertIn(
            "SDL3=0", self.make_argv(),
            msg=("the Makefile defaults SDL3=1 whenever TILES=1 and "
                 "then raises a hard error when pkg-config cannot "
                 "satisfy SDL3 >= 3.4.0: without this the build does "
                 "not degrade, it aborts"))

    def test_no_forbidden_flag_is_passed(self):
        self.run_launch("build")
        argv = self.make_argv()
        for flag in FORBIDDEN_MAKE_ARGS:
            with self.subTest(flag=flag):
                self.assertNotIn(flag, argv)
        for argument in argv:
            with self.subTest(argument=argument):
                self.assertFalse(
                    argument.startswith("TESTS="),
                    msg="TESTS=0 must never be passed")
                self.assertFalse(
                    argument.startswith("NATIVE="),
                    msg="NATIVE must not be pinned by this pipeline")

    def test_the_parallelism_is_bounded_by_memory_not_cpu(self):
        self.run_launch("build", PLAYTHROUGH_BUILD_JOBS="3")
        self.assertIn("-j3", self.make_argv())

    def test_a_wider_build_is_clamped_loudly(self):
        status, _, err = self.run_launch(
            "build", PLAYTHROUGH_BUILD_JOBS="64")
        self.assertEqual(status, EX_OK)
        self.assertIn(
            "-j3", self.make_argv(),
            msg=("the cap is a memory limit, not a CPU one: a wider "
                 "build is OOM-killed, which surfaces as 'Killed' "
                 "rather than as a compile error"))
        self.assertIn("exceeds", err)
        self.assertIn("cap", err)

    def test_the_sanctioned_compiler_is_used_and_named(self):
        """And named by the path it was VERIFIED at, not by bare name.

        env.sh's playthrough_resolve_tool checks that neither the
        binary nor any directory above it is writable by anyone else,
        and exports where it found it.  That resolved path is what
        reaches make, so a later change to PATH cannot substitute a
        different compiler for the one that was actually checked.
        """
        self.run_launch("build")
        resolved = os.path.join(self.bin, "g++-14")
        self.assertIn(
            "COMPILER=%s" % resolved, self.make_argv(),
            msg="the Makefile's own COMPILER variable")
        self.assertEqual(
            self.calls("make-env"), ["CXX=%s" % resolved],
            msg=("CXX reaches make through the environment, via "
                 "`env CXX=... make ...`, which is what selects the "
                 "compiler the tree is documented to build with"))

    def test_a_compiler_of_the_wrong_major_is_refused(self):
        status, _, err = self.run_launch(
            "build", PLAYTHROUGH_COMPILER="g++-15")
        self.assertEqual(status, EX_PREREQ)
        self.assertIn("major version 15", err)
        self.assertIn(
            "-Werror", err,
            msg=("a newer GCC diagnoses engine source that this "
                 "pipeline is not allowed to edit, so refusing beats "
                 "spending a 25-minute build to fail there"))
        self.assertEqual(self.calls("make"), [])

    def test_an_unverifiable_compiler_is_refused(self):
        status, _, err = self.run_launch(
            "build", STUB_COMPILER_VERSION="")
        self.assertEqual(status, EX_PREREQ)
        self.assertIn("did not report a usable version", err)

    def test_an_unsupported_compiler_can_be_forced_with_a_warning(self):
        status, _, err = self.run_launch(
            "build", PLAYTHROUGH_COMPILER="g++-15",
            PLAYTHROUGH_ALLOW_ANY_COMPILER="1")
        self.assertEqual(status, EX_OK)
        self.assertIn("proceeding with", err)
        resolved = os.path.join(self.bin, "g++-15")
        self.assertIn("COMPILER=%s" % resolved, self.make_argv())
        self.assertEqual(self.calls("make-env"), ["CXX=%s" % resolved])

    def test_a_compiler_that_is_not_installed_is_refused(self):
        os.unlink(os.path.join(self.bin, "g++-14"))
        status, _, err = self.run_launch("build")
        self.assertEqual(status, EX_PREREQ)
        self.assertIn("apt-get install -y g++-14", err)

    def test_a_missing_build_tool_stops_before_anything_changes(self):
        os.unlink(os.path.join(self.bin, "ccache"))
        status, _, err = self.run_launch("build")
        self.assertEqual(status, EX_PREREQ)
        self.assertIn("ccache", err)
        self.assertEqual(self.calls("make"), [])

    def test_a_failed_build_is_reported_as_a_build_failure(self):
        status, _, err = self.run_launch(
            "build", STUB_MAKE_RC="2", STUB_MAKE_BUILDS="0")
        self.assertEqual(status, EX_BUILD)
        self.assertEqual(len(self.calls("make")), 1)

    def test_an_existing_binary_is_reused_rather_than_rebuilt(self):
        self.install_game()
        status, out, err = self.run_launch("build")
        self.assertEqual(status, EX_OK)
        self.assertEqual(
            self.calls("make"), [],
            msg="a 25-minute build is not run for nothing")
        self.assertIn("reusing the existing binary", err)


class TestTheTilesProof(LaunchFixture):
    """The binary settles tiles versus curses from its own mouth."""

    def test_a_tiles_binary_is_confirmed_and_reported(self):
        self.install_game()
        status, out, err = self.run_launch("build")
        self.assertEqual(status, EX_OK)
        emitted = self.emitted(out)
        self.assertIn("+tiles", emitted["PLAYTHROUGH_GAME_VERSION"])
        self.assertIn("tiles build confirmed", err)

    def test_a_curses_binary_is_refused(self):
        self.install_game(version=CURSES_LINE)
        status, _, err = self.run_launch("build")
        self.assertEqual(status, EX_NOT_TILES)
        self.assertIn(
            "does not contain '+tiles'", err,
            msg=("the curses build is never an acceptable substitute, "
                 "and nothing else is trusted -- not the file name, "
                 "not the presence of gfx/"))
        self.assertIn("Rebuild with TILES=1 SOUND=1 SDL3=0", err)

    def test_a_silent_binary_cannot_be_verified(self):
        self.write(self.game, "#!/bin/bash\nexit 0\n", mode=0o755)
        status, _, err = self.run_launch("build")
        self.assertEqual(status, EX_NOT_TILES)
        self.assertIn("printed nothing", err)

    def test_a_binary_that_is_not_executable_is_not_a_binary(self):
        self.write(self.game, "#!/bin/bash\nexit 0\n", mode=0o644)
        status, _, err = self.run_launch("build")
        self.assertEqual(status, EX_OK)
        self.assertEqual(
            len(self.calls("make")), 1,
            msg=("a file that cannot run is not a binary, so it is "
                 "rebuilt rather than probed for '+tiles'"))
        self.assertNotIn("reusing the existing binary", err)

    def test_a_binary_that_cannot_be_made_executable_is_refused(self):
        # The one path that reaches assert_tiles_binary's -x branch: a
        # build that reports success without leaving a runnable file.
        self.write(self.game, "#!/bin/bash\nexit 0\n", mode=0o644)
        status, _, err = self.run_launch("build", STUB_MAKE_BUILDS="0")
        self.assertEqual(status, EX_PREREQ)
        self.assertIn("is not", err)
        self.assertIn("executable", err)

    def test_the_proof_is_repeated_after_a_build(self):
        status, out, err = self.run_launch(
            "build", STUB_VERSION=CURSES_LINE)
        self.assertEqual(
            status, EX_NOT_TILES,
            msg=("the assertion runs after the build too, so a build "
                 "that produced the wrong binary is caught"))
        self.assertEqual(len(self.calls("make")), 1)

    def test_the_version_probe_needs_no_display(self):
        self.install_game()
        status, _, _ = self.run_launch("build", STUB_XDPYINFO_RC="1")
        self.assertEqual(
            status, EX_OK,
            msg=("--version is handled while the command line is still "
                 "being parsed, before any window is created"))


class TestTheResumeProbe(LaunchFixture):
    """If a save exists it MUST be continued."""

    def probe(self, **overrides):
        """Run the probe subcommand and return its emitted keys."""
        status, out, err = self.run_launch("probe", **overrides)
        return status, self.emitted(out), err

    def test_no_save_at_all_creates_a_character(self):
        status, emitted, err = self.probe()
        self.assertEqual(status, EX_OK)
        self.assertEqual(emitted["PLAYTHROUGH_SESSION_MODE"], "create")
        self.assertEqual(emitted["PLAYTHROUGH_SAVE_WORLD"], "")
        self.assertEqual(emitted["PLAYTHROUGH_SAVE_WORLD_COUNT"], "0")
        self.assertEqual(emitted["PLAYTHROUGH_SAVE_CHAR_COUNT"], "0")
        self.assertEqual(
            emitted["PLAYTHROUGH_SAVE_RESUMABLE_COUNT"], "0")
        self.assertIn("custom point-buy creator", err)

    def test_one_world_with_one_character_is_resumed(self):
        self.install_world("Sunnyside", ("#c3VydmlvdXI=.sav",))
        status, emitted, err = self.probe()
        self.assertEqual(status, EX_OK)
        self.assertEqual(emitted["PLAYTHROUGH_SESSION_MODE"], "resume")
        self.assertEqual(emitted["PLAYTHROUGH_SAVE_WORLD"],
                         "Sunnyside")
        self.assertEqual(emitted["PLAYTHROUGH_SAVE_CHAR_COUNT"], "1")
        self.assertIn("MUST be continued", err)

    def test_a_compressed_character_save_counts_too(self):
        self.install_world("Sunnyside", ("#c3VydmlvdXI=.sav.zzip",))
        status, emitted, _ = self.probe()
        self.assertEqual(
            emitted["PLAYTHROUGH_SESSION_MODE"], "resume",
            msg=("WORLD_COMPRESSION2 makes the character file "
                 "#<b64>.sav.zzip, and a probe that counted only .sav "
                 "would start a second survivor over the first"))
        self.assertEqual(emitted["PLAYTHROUGH_SAVE_CHAR_COUNT"], "1")

    def test_one_character_is_not_counted_twice(self):
        # A .sav and a .sav.zzip for the SAME character are ONE
        # survivor.  A naive two-glob sum reported two, which then read
        # as an ambiguous save and warned about choosing between
        # survivors that did not both exist.
        self.install_world("Sunnyside",
                           ("#c3VydmlvdXI=.sav",
                            "#c3VydmlvdXI=.sav.zzip"))
        status, emitted, err = self.probe()
        self.assertEqual(emitted["PLAYTHROUGH_SESSION_MODE"], "resume")
        self.assertEqual(
            emitted["PLAYTHROUGH_SAVE_RESUMABLE_COUNT"], "1",
            msg="one world holds characters, so the choice is not "
                "ambiguous")
        self.assertEqual(
            emitted["PLAYTHROUGH_SAVE_CHAR_COUNT"], "1",
            msg="and one survivor is one survivor, in either spelling")
        self.assertNotIn("distinct character", err)

    def test_the_storage_form_is_reported_not_assumed(self):
        """Which spelling the save actually uses, per world and overall.

        WORLD_COMPRESSION2 is seeded false so this run's own save is a
        plain `.sav`, but the probe runs BEFORE any seeding on a resumed
        run and the world may not have been created under that seed at
        all -- so the form is read off the disk.
        """
        self.install_world("Plain", ("#a.sav",))
        status, emitted, _ = self.probe()
        self.assertEqual(emitted["PLAYTHROUGH_SAVE_CHAR_FORMS"], ".sav")

        self.setUp()
        self.install_world("Zipped", ("#a.sav.zzip",))
        _, emitted, _ = self.probe()
        self.assertEqual(
            emitted["PLAYTHROUGH_SAVE_CHAR_FORMS"], ".sav.zzip")

        # ONE world holding two survivors, one in each spelling.  Two
        # worlds would be the ambiguity refusal, which emits nothing --
        # a different behaviour, covered by its own test.
        self.setUp()
        self.install_world("Mixed", ("#a.sav", "#b.sav.zzip"))
        _, emitted, _ = self.probe()
        self.assertEqual(
            emitted["PLAYTHROUGH_SAVE_CHAR_FORMS"], ".sav,.sav.zzip",
            msg="both forms are reported when both are present")

        # And across worlds, when only one of them is resumable, so the
        # fact still describes the save TREE and not the last directory
        # the loop happened to scan.
        self.setUp()
        self.install_world("Zipped", ("#a.sav.zzip",))
        self.install_world("Empty")
        _, emitted, _ = self.probe()
        self.assertEqual(
            emitted["PLAYTHROUGH_SAVE_CHAR_FORMS"], ".sav.zzip")

        self.setUp()
        _, emitted, _ = self.probe()
        self.assertEqual(
            emitted["PLAYTHROUGH_SAVE_CHAR_FORMS"], "",
            msg="empty when no character file exists yet")

    def test_the_forms_helper_can_be_called_directly(self):
        holder = self.install_world("Sunnyside", ("#a.sav",))
        status, out, _ = self.run_sourced(
            'character_save_forms "%s/"' % holder)
        self.assertEqual(status, 0)
        self.assertEqual(out.strip(), ".sav")
        holder = self.install_world("Both",
                                    ("#a.sav", "#b.sav.zzip"))
        _, out, _ = self.run_sourced(
            'character_save_forms "%s/"' % holder)
        self.assertEqual(out.strip(), ".sav,.sav.zzip")

    def test_a_world_with_no_character_is_not_resumable(self):
        self.install_world("Interrupted")
        status, emitted, err = self.probe()
        self.assertEqual(status, EX_OK)
        self.assertEqual(
            emitted["PLAYTHROUGH_SESSION_MODE"], "create",
            msg=("a world is written as soon as it is created, so this "
                 "is a run interrupted during character creation; "
                 "loading it would open an empty character list"))
        self.assertEqual(emitted["PLAYTHROUGH_SAVE_WORLD_COUNT"], "1")
        self.assertEqual(
            emitted["PLAYTHROUGH_SAVE_RESUMABLE_COUNT"], "0")
        self.assertIn("NO character save", err)

    def test_a_directory_without_a_master_save_is_not_a_world(self):
        self.install_world("NotAWorld", ("#abc.sav",), master=False)
        status, emitted, err = self.probe()
        self.assertEqual(emitted["PLAYTHROUGH_SAVE_WORLD_COUNT"], "0")
        self.assertEqual(emitted["PLAYTHROUGH_SESSION_MODE"], "create")
        self.assertIn("has no master.gsav", err)

    def test_two_resumable_worlds_are_refused_rather_than_guessed(self):
        self.install_world("Alpha", ("#a.sav",))
        self.install_world("Bravo", ("#b.sav",))
        status, _, err = self.run_launch("probe")
        self.assertEqual(status, EX_LAYOUT)
        self.assertIn(
            "directory order is locale- and", err.replace("\n", " "),
            msg=("a guess could continue a different survivor on the "
                 "next run of the same command"))
        self.assertIn("PLAYTHROUGH_RESUME_WORLD", err)

    def test_an_explicit_world_resolves_the_ambiguity(self):
        self.install_world("Alpha", ("#a.sav",))
        self.install_world("Bravo", ("#b.sav",))
        status, emitted, err = self.probe(
            PLAYTHROUGH_RESUME_WORLD="Bravo")
        self.assertEqual(status, EX_OK)
        self.assertEqual(emitted["PLAYTHROUGH_SAVE_WORLD"], "Bravo")
        self.assertIn("chosen explicitly", err)

    def test_an_explicit_world_that_is_not_resumable_is_refused(self):
        self.install_world("Alpha", ("#a.sav",))
        status, _, err = self.run_launch(
            "probe", PLAYTHROUGH_RESUME_WORLD="Charlie")
        self.assertEqual(status, EX_LAYOUT)
        self.assertIn("is not a resumable world", err)
        self.assertIn("Alpha", err)

    def test_a_second_survivor_in_the_chosen_world_warns(self):
        """A warning, not a refusal, and the asymmetry is deliberate.

        Which WORLD to open is a decision this script has to make and
        must not guess.  Which survivor to load happens inside the
        game's own character list, where the operator sees the names --
        so it is surfaced and left to them.
        """
        self.install_world("Sunnyside", ("#a.sav", "#b.sav"))
        status, emitted, err = self.probe()
        self.assertEqual(status, EX_OK)
        self.assertEqual(emitted["PLAYTHROUGH_SESSION_MODE"], "resume")
        self.assertEqual(emitted["PLAYTHROUGH_SAVE_CHAR_COUNT"], "2")
        self.assertIn("2 distinct character", err)
        self.assertIn("do not create another", err)

    def test_the_counts_span_every_world(self):
        self.install_world("Alpha", ("#a.sav", "#b.sav"))
        self.install_world("Empty")
        status, emitted, _ = self.probe()
        self.assertEqual(emitted["PLAYTHROUGH_SAVE_WORLD_COUNT"], "2")
        self.assertEqual(emitted["PLAYTHROUGH_SAVE_CHAR_COUNT"], "2")
        self.assertEqual(
            emitted["PLAYTHROUGH_SAVE_RESUMABLE_COUNT"], "1")

    def test_a_file_that_is_not_a_character_save_is_ignored(self):
        holder = self.install_world("Sunnyside")
        for name in ("maps.zzip", "worldoptions.json", "#abc.log",
                     "#abc.shortcuts", "notes.txt"):
            self.write(os.path.join(holder, name), "x\n")
        status, emitted, _ = self.probe()
        self.assertEqual(
            emitted["PLAYTHROUGH_SESSION_MODE"], "create",
            msg=("only #*.sav and #*.sav.zzip are character saves; a "
                 "log or a shortcuts file is not one"))

    def test_the_character_counter_can_be_called_directly(self):
        holder = self.install_world("Sunnyside",
                                    ("#a.sav", "#b.sav.zzip"))
        status, out, _ = self.run_sourced(
            'count_character_saves "%s/"' % holder)
        self.assertEqual(status, 0)
        self.assertEqual(out.strip(), "2")

    def test_the_counter_answers_zero_for_an_empty_directory(self):
        holder = self.install_world("Sunnyside")
        status, out, _ = self.run_sourced(
            'count_character_saves "%s/"' % holder)
        self.assertEqual(out.strip(), "0")


class TestTheWindowLookup(LaunchFixture):
    """By class, and only by class."""

    def test_the_search_is_by_class(self):
        self.install_game()
        self.run_launch("status", STUB_WINDOW_IDS="")
        searches = [call for call in self.calls("xdotool")
                    if call.startswith("search")]
        self.assertTrue(searches)
        for call in searches:
            with self.subTest(call=call):
                self.assertIn("--class cataclysm-tiles", call)
                self.assertNotIn(
                    "--name", call,
                    msg=("xdotool search --name 'Cataclysm' returns "
                         "EMPTY for this window even though xwininfo "
                         "lists it, so name matching is not an "
                         "available alternative"))

    def test_no_window_is_an_ordinary_answer(self):
        self.install_game()
        status, out, _ = self.run_launch("status", STUB_WINDOW_IDS="")
        self.assertEqual(status, EX_OK)
        self.assertEqual(
            self.emitted(out)["PLAYTHROUGH_GAME_RUNNING"], "0",
            msg=("xdotool search exits non-zero when nothing matches, "
                 "which is an answer and not an error"))

    def test_the_window_ids_helper_returns_what_xdotool_found(self):
        status, out, _ = self.run_sourced(
            "game_window_ids", STUB_WINDOW_IDS="4194305 4194306")
        self.assertEqual(status, 0)
        self.assertEqual(out.split(), ["4194305", "4194306"])

    def test_a_launch_with_no_window_fails_as_a_window_fault(self):
        self.ready_to_launch()
        status, _, err = self.run_launch(
            "launch", STUB_WINDOW_IDS="",
            PLAYTHROUGH_WINDOW_TIMEOUT="1")
        self.assertEqual(
            status, EX_WINDOW,
            msg=("a game that never opens a window is a window fault, "
                 "not a silent success"))


class TestTheResumeUiState(LaunchFixture):
    """A resumed session must START from a menu, provably.

    The resume branch of the capture launch used to differ from the
    create branch by one log line: the same process at the same screen,
    with "do not create a new character" left entirely to a key driver
    that could not tell one screen from another.  So the launcher now
    establishes the state a resumed session begins in and VERIFIES it
    with a diagnostic capture -- one whose PNG is withdrawn out of the
    working tree and whose exit status is 9, so it can never be mistaken
    for a frame of the record.
    """

    def install_capture_stub(self, clock="", phrase="", date="",
                             status=9):
        """A capture.sh stand-in that reports one sidebar reading."""
        path = os.path.join(self.tooling, "capture.sh")
        self.write(path, (
            "#!/bin/sh\n"
            "printf 'CAPTURE_MODE=diagnostic\\n'\n"
            "printf 'FRAME_INDEX=%%s\\n' \"${FRAME_INDEX-}\"\n"
            "printf 'FRAME_FILE=\\n'\n"
            "printf 'CLOCK_STATUS=read\\n'\n"
            "printf 'CLOCK=%s\\n'\n"
            "printf 'TIME_PHRASE=%s\\n'\n"
            "printf 'CLOCK_DATE=\\n'\n"
            "printf 'DATE=%s\\n'\n"
            "printf 'DATE_STATUS=read\\n'\n"
            "exit %d\n" % (clock, phrase, date, status)))
        os.chmod(path, 0o755)
        return path

    def verify(self, **overrides):
        """Call verify_resume_ui_state with a pinned world."""
        after = ('SAVE_WORLD="Sunnyside"\n'
                 'SAVE_CHAR_COUNT=1\n'
                 'verify_resume_ui_state\n'
                 'printf "STATUS=%s\\n" "$?"\n'
                 'printf "STATE=%s\\n" "${INITIAL_UI_STATE}"\n')
        return self.run_sourced(after, **overrides)

    def test_a_menu_screen_is_accepted_and_declared(self):
        self.install_capture_stub()
        status, out, err = self.verify()
        self.assertEqual(status, 0)
        emitted = self.emitted(out)
        self.assertEqual(emitted["STATUS"], "0")
        self.assertEqual(emitted["STATE"], "main-menu-load-required")
        self.assertIn("RESUME UI STATE verified", err)
        self.assertIn("must LOAD that character", err)

    def test_a_screen_already_in_the_world_is_refused(self):
        """A sidebar reading means a survivor is already loaded.

        For a launch this script has just taken, that means the engine is
        not where a resumed session has to begin -- and the load itself
        must be captured, one frame per keystroke, rather than having
        happened before the recording started.
        """
        self.install_capture_stub(
            clock="08:15:33", date="Thursday, May 20")
        status, out, err = self.verify()
        self.assertEqual(status, EX_LAYOUT)
        self.assertNotIn("STATE=", out)
        self.assertIn("ALREADY IN THE WORLD", err)
        self.assertIn("08:15:33", err)

    def test_a_coarse_time_phrase_counts_as_the_world_too(self):
        """No watch does not mean no sidebar.

        display::time_string() falls back to a coarse phrase without a
        time-telling device (src/display.cpp:159-185), and that phrase is
        still drawn only for a loaded character.
        """
        self.install_capture_stub(phrase="Around dawn")
        status, _, err = self.verify()
        self.assertEqual(status, EX_LAYOUT)
        self.assertIn("ALREADY IN THE WORLD", err)

    def test_an_unreadable_probe_is_recorded_as_unverified(self):
        """It does not silently pass as verified.

        A probe that could not be taken has established nothing, so the
        state says so -- and session.py's own refusal of every
        new-survivor hotkey stands whatever this reports.
        """
        self.install_capture_stub(status=4)
        status, out, err = self.verify()
        self.assertEqual(status, 0)
        self.assertEqual(self.emitted(out)["STATE"], "unverified")
        self.assertIn("recorded as unverified", err)

    def test_the_declared_state_reaches_the_machine_channel(self):
        """emit_launch_facts publishes it, like every other fact."""
        after = ('LAUNCH_PHASE="capture"\n'
                 'INITIAL_UI_STATE="main-menu-load-required"\n'
                 'emit_launch_facts\n')
        status, out, _ = self.run_sourced(after)
        self.assertEqual(status, 0)
        self.assertEqual(
            self.emitted(out)["PLAYTHROUGH_INITIAL_UI_STATE"],
            "main-menu-load-required")


class TestTheCaptureGeometryGate(LaunchFixture):
    """A window smaller than the grid must not be captured."""

    def geometry(self, mode, width, height, grid=""):
        """Call check_capture_geometry with a chosen window size.

        `die` exits the shell, so a refusal is visible as the exit
        status of the sourced program and STATUS= never prints.
        """
        after = (
            "%s"
            'WINDOW_ID=4194305\n'
            'WINDOW_WIDTH="%s"\nWINDOW_HEIGHT="%s"\n'
            'WINDOW_GEOMETRY="%sx%s+0+4"\n'
            "check_capture_geometry %s\n"
            "printf 'STATUS=%%s\\n' \"$?\"\n"
            % (grid, width, height, width or 0, height or 0, mode))
        return self.run_sourced(after)

    def test_the_contracted_window_matches_the_grid_exactly(self):
        status, out, err = self.geometry("strict", 1920, 1072)
        self.assertEqual(status, 0)
        self.assertIn("STATUS=0", out)
        self.assertIn("matches the 240x67 grid exactly", err)

    def test_a_larger_window_covers_the_grid(self):
        status, out, err = self.geometry("strict", 1920, 1080)
        self.assertEqual(status, 0)
        self.assertIn("STATUS=0", out)
        self.assertIn("covers the 1920x1072 grid", err)

    def test_the_first_launch_window_is_refused_in_strict_mode(self):
        status, out, err = self.geometry("strict", 640, 384)
        self.assertEqual(status, EX_WINDOW)
        self.assertNotIn("STATUS=", out)
        self.assertIn("SMALLER than the 1920x1072 grid", err)
        self.assertIn(
            "TERMINAL_X 80 and TERMINAL_Y 24", err,
            msg=("a 640x384 window means options.json still holds the "
                 "compiled defaults, and the message says exactly "
                 "that"))

    def test_the_same_window_is_a_warning_in_warn_mode(self):
        status, out, err = self.geometry("warn", 640, 384)
        self.assertEqual(status, 0)
        self.assertIn(
            "STATUS=0", out,
            msg="warn mode reports and carries on")
        self.assertIn("SMALLER than", err)

    def test_a_window_short_in_only_one_dimension_is_refused(self):
        status, out, err = self.geometry("strict", 1920, 1071)
        self.assertEqual(
            status, EX_WINDOW,
            msg=("one row short still crops the sidebar, so the test "
                 "is on each dimension and not on the area"))

    def test_an_unreadable_geometry_is_refused_in_strict_mode(self):
        status, out, err = self.geometry("strict", "", "")
        self.assertEqual(status, EX_WINDOW)
        self.assertIn(
            "could not be read", err,
            msg=("this session would be photographed without ever "
                 "having verified what is on screen"))

    def test_a_half_read_geometry_is_refused_too(self):
        for width, height in ((1920, ""), ("", 1072)):
            with self.subTest(width=width, height=height):
                status, _, err = self.geometry("strict", width, height)
                self.assertEqual(status, EX_WINDOW)
                self.assertIn("could not be read", err)

    def test_an_unreadable_geometry_is_a_warning_in_warn_mode(self):
        status, out, err = self.geometry("warn", "", "")
        self.assertEqual(status, 0)
        self.assertIn("STATUS=0", out)
        self.assertIn("geometry is unknown", err)

    def test_the_wanted_grid_is_computed_from_the_contract(self):
        # env.sh exports the grid, so it is overridden here rather than
        # in the environment: what is being proven is that the bound is
        # TERMINAL_X * FONT_WIDTH by TERMINAL_Y * FONT_HEIGHT and not a
        # hard-coded 1920x1072.
        grid = ("PLAYTHROUGH_TERMINAL_X=160\n"
                "PLAYTHROUGH_TERMINAL_Y=50\n")
        status, out, err = self.geometry("strict", 1280, 800,
                                         grid=grid)
        self.assertEqual(status, 0)
        self.assertIn("matches the 160x50 grid exactly", err)

    def test_a_narrower_grid_admits_a_smaller_window(self):
        grid = ("PLAYTHROUGH_TERMINAL_X=80\n"
                "PLAYTHROUGH_TERMINAL_Y=24\n")
        status, out, err = self.geometry("strict", 640, 384, grid=grid)
        self.assertEqual(
            status, 0,
            msg=("640x384 is refused because the grid says 240x67, "
                 "not because 640x384 is small"))


class TestTheTilesetResolution(LaunchFixture):
    """The id is the NAME: field, never the directory name."""

    def test_the_required_tileset_is_used_when_installed(self):
        self.install_tileset("MShockXotto+", MSX_ID, MSX_VIEW)
        self.install_tileset("ASCIITileset", ASCII_ID, "ASCII")
        status, out, err = self.run_launch("tileset")
        self.assertEqual(status, EX_OK)
        emitted = self.emitted(out)
        self.assertEqual(emitted["PLAYTHROUGH_TILESET_RESOLVED"],
                         MSX_ID)
        self.assertEqual(emitted["PLAYTHROUGH_TILESET_VIEW"], MSX_VIEW)
        self.assertIn(
            "origin=required-installed", err,
            msg=("ASCIITiles is installed alongside it and is not a "
                 "candidate: the required pack is required, not "
                 "preferred"))

    def test_the_required_pack_is_installed_when_only_pre_placed(self):
        self.install_pack("MShockXotto+", MSX_ID, MSX_VIEW)
        self.install_tileset("ASCIITileset", ASCII_ID, "ASCII")
        status, out, err = self.run_launch("tileset")
        self.assertEqual(status, EX_OK)
        emitted = self.emitted(out)
        self.assertEqual(emitted["PLAYTHROUGH_TILESET_RESOLVED"],
                         MSX_ID)
        self.assertEqual(emitted["PLAYTHROUGH_TILESET_ORIGIN"],
                         "required-from-pack")
        self.assertTrue(os.path.isfile(os.path.join(
            self.checkout, "gfx", "MShockXotto+", "tileset.txt")))

    def test_an_installed_pack_is_left_exactly_as_it_is(self):
        self.install_pack("MShockXotto+", MSX_ID, MSX_VIEW)
        self.install_tileset("MShockXotto+", MSX_ID, MSX_VIEW)
        status, out, _ = self.run_launch("tileset")
        self.assertEqual(
            self.emitted(out)["PLAYTHROUGH_TILESET_ORIGIN"],
            "required-installed")
        self.assertFalse(
            os.path.exists(os.path.join(
                self.checkout, "gfx", "MShockXotto+",
                "tile_config.json")),
            msg="an already-installed tileset is never overwritten")

    def test_no_partial_directory_survives_a_pack_install(self):
        self.install_pack("MShockXotto+", MSX_ID, MSX_VIEW)
        self.run_launch("tileset")
        leftovers = [name for name
                     in os.listdir(os.path.join(self.checkout, "gfx"))
                     if ".partial." in name]
        self.assertEqual(
            leftovers, [],
            msg=("the copy lands aside and is renamed, so an "
                 "interrupted install cannot leave a half-populated "
                 "tileset that a later scan treats as installed"))

    def test_the_checkout_s_own_tileset_is_not_a_fallback(self):
        self.install_tileset("ASCIITileset", ASCII_ID, "ASCII")
        status, out, err = self.run_launch("tileset")
        self.assertEqual(
            status, EX_TILESET,
            msg=("the AAP requires MSXotto+ specifically, so a "
                 "checkout that has only its own ASCIITiles is a "
                 "stop and never a quiet substitution"))
        self.assertNotIn(
            "PLAYTHROUGH_TILESET_RESOLVED", self.emitted(out),
            msg="nothing is resolved when the requirement is unmet")
        joined = " ".join(err.split())
        self.assertIn(
            "DIAGNOSIS ONLY", joined,
            msg=("falling back to ASCIITiles would produce a "
                 "plausible film that silently failed the "
                 "requirement, so the substitution exists only for "
                 "somebody debugging the pipeline"))
        self.assertIn(
            "PLAYTHROUGH_ALLOW_TILESET_FALLBACK=1", joined,
            msg=("and it has to be asked for by name -- a refusal "
                 "that does not say how to proceed deliberately is a "
                 "dead end"))
        self.assertIn(
            ASCII_ID, err,
            msg=("what IS installed is reported, so the refusal is "
                 "diagnosable without a second command"))

    def test_no_tileset_at_all_is_refused(self):
        status, _, err = self.run_launch("tileset")
        self.assertEqual(status, EX_TILESET)
        self.assertIn("the required tileset", err)
        self.assertIn("no tileset.txt at all", err)

    def test_the_directory_name_is_never_the_id(self):
        self.install_tileset("MShockXotto+", MSX_ID, MSX_VIEW)
        status, out, _ = self.run_launch("tileset")
        emitted = self.emitted(out)
        self.assertEqual(
            emitted["PLAYTHROUGH_TILESET_RESOLVED"], MSX_ID,
            msg=("gfx/ASCIITileset declares NAME: ASCIITiles, so "
                 "writing the directory name into the TILES option "
                 "would select nothing"))
        self.assertTrue(
            emitted["PLAYTHROUGH_TILESET_DIR"].endswith(
                "gfx/MShockXotto+"),
            msg="the directory is reported separately, as a fact")

    def test_only_the_two_engine_fields_are_read(self):
        conf = self.install_tileset("Pack", "PackId", "Pack View")
        status, out, _ = self.run_sourced(
            'tileset_field "%s" NAME\ntileset_field "%s" VIEW\n'
            'tileset_field "%s" JSON || printf "refused\\n"'
            % (conf, conf, conf))
        self.assertEqual(
            out.split("\n")[:3],
            ["PackId", "Pack View", "refused"],
            msg="NAME and VIEW are the only fields this pipeline reads")

    def test_the_first_declaration_of_a_field_wins(self):
        conf = os.path.join(self.checkout, "gfx", "Pack",
                            "tileset.txt")
        self.write(conf, "NAME: First\nNAME: Second\n")
        status, out, _ = self.run_sourced(
            'tileset_field "%s" NAME' % conf)
        self.assertEqual(out.strip(), "First")

    def test_trailing_whitespace_is_not_part_of_an_id(self):
        conf = os.path.join(self.checkout, "gfx", "Pack",
                            "tileset.txt")
        self.write(conf, "NAME:   Padded   \r\n")
        status, out, _ = self.run_sourced(
            'tileset_field "%s" NAME' % conf)
        self.assertEqual(
            out.strip("\n"), "Padded",
            msg=("a CRLF or a trailing space would be written into the "
                 "TILES option and would match no installed tileset"))

    def test_a_pack_with_no_name_is_not_a_tileset(self):
        self.write(
            os.path.join(self.checkout, "gfx", "Broken",
                         "tileset.txt"),
            "VIEW: Nameless\n")
        self.write(
            os.path.join(self.checkout, "gfx", "NotEvenAPack",
                         "readme.txt"),
            "no tileset.txt here\n")
        self.install_tileset("ASCIITileset", ASCII_ID)
        status, out, _ = self.run_sourced(
            'scan_installed_tilesets\n'
            'printf "COUNT=%s\\n" "${#TILESET_NAMES[@]}"\n'
            'printf "ID=%s\\n" "${TILESET_NAMES[0]}"')
        self.assertIn("COUNT=1", out)
        self.assertIn("ID=%s" % ASCII_ID, out)

    def test_a_tileset_is_matched_on_its_display_name_too(self):
        self.install_tileset("Pack", "SomeId", MSX_ID)
        status, out, _ = self.run_launch("tileset")
        self.assertEqual(
            self.emitted(out)["PLAYTHROUGH_TILESET_RESOLVED"],
            "SomeId",
            msg="matching is a literal test against NAME or VIEW")

    def test_matching_is_literal_and_never_a_pattern(self):
        self.install_tileset("Pack", "MshockXottoplu", "X")
        self.install_tileset("Other", ASCII_ID)
        status, out, err = self.run_launch("tileset")
        self.assertEqual(
            status, EX_TILESET,
            msg=("a prefix is not a match; real ids carry characters "
                 "such as '+' that a pattern would mis-read, so a "
                 "near-miss id is an absent tileset"))
        self.assertNotIn(
            "PLAYTHROUGH_TILESET_RESOLVED", self.emitted(out),
            msg="a one-character-short id resolves nothing at all")
        self.assertIn(
            "MshockXottoplu ", err,
            msg=("the near-miss is listed in the inventory, so it is "
                 "visibly seen and rejected rather than overlooked"))

    def test_the_substitute_has_to_be_asked_for_by_name(self):
        """The sanctioned diagnostic path, and its loud announcement.

        A host with no pack can still bring the game up to be looked at,
        but the run says so on stderr and records origin=fallback, so a
        diagnostic launch cannot be mistaken for a compliant one.
        """
        self.install_tileset("ASCIITileset", ASCII_ID, "ASCII")
        status, out, err = self.run_launch(
            "tileset", PLAYTHROUGH_ALLOW_TILESET_FALLBACK="1")
        self.assertEqual(status, EX_OK)
        emitted = self.emitted(out)
        self.assertEqual(emitted["PLAYTHROUGH_TILESET_RESOLVED"],
                         ASCII_ID)
        self.assertEqual(emitted["PLAYTHROUGH_TILESET_ORIGIN"],
                         "fallback")
        self.assertIn("DIAGNOSTIC CONFIGURATION", err)
        self.assertIn("do not record a session under it", err)

    def test_naming_a_substitute_does_not_authorise_one(self):
        """$..._TILESET_FALLBACK says WHICH, never WHETHER."""
        self.install_tileset("HouseStyle", "HouseStyle", "House")
        status, _, err = self.run_launch(
            "tileset", PLAYTHROUGH_TILESET_FALLBACK="HouseStyle")
        self.assertEqual(
            status, EX_TILESET,
            msg=("naming the substitute is not asking for it; only "
                 "PLAYTHROUGH_ALLOW_TILESET_FALLBACK=1 does that"))
        self.assertIn("PLAYTHROUGH_ALLOW_TILESET_FALLBACK=1", err)

    def test_a_malformed_fallback_switch_is_refused(self):
        """Every reading of it that is not 1 is silently 0."""
        for value in ("yes", "true", "2", "0 "):
            with self.subTest(value=value):
                status, _, err = self.run_launch(
                    "tileset", PLAYTHROUGH_ALLOW_TILESET_FALLBACK=value)
                self.assertEqual(status, EX_USAGE)
                self.assertIn("neither 0 nor 1", err)

    def test_a_pack_on_an_untrustworthy_path_is_refused(self):
        """The ingestion gate, with the condition arranged.

        The sandbox is private, so the untrustworthy state is created
        rather than inherited: the staged pack is made world-writable,
        which is exactly the state in which another account can replace
        an entry between the check and the copy.  Artwork from such a
        path is not copied into the tree the game loads.
        """
        self.install_pack("MShockXotto+", MSX_ID, MSX_VIEW)
        self.install_tileset("ASCIITileset", ASCII_ID, "ASCII")
        os.chmod(self.pack, 0o777)
        status, _, err = self.run_launch(
            "tileset", PLAYTHROUGH_ALLOW_UNVERIFIED_TILESET_PACK=None)
        self.assertEqual(status, EX_TILESET)
        self.assertIn("group- or world-writable", err)
        self.assertIn("PLAYTHROUGH_ALLOW_UNVERIFIED_TILESET_PACK=1",
                      err)
        self.assertFalse(
            os.path.exists(os.path.join(
                self.checkout, "gfx", "MShockXotto+")),
            msg="nothing is copied when the provenance is refused")

    def test_a_pack_with_no_manifest_is_refused_regardless(self):
        """The declaration covers the HOST, never the bytes."""
        self.install_pack("MShockXotto+", MSX_ID, MSX_VIEW,
                          manifest=False)
        status, _, err = self.run_launch("tileset")
        self.assertEqual(status, EX_TILESET)
        self.assertIn("carries no", err)
        self.assertIn("sha256", err)
        self.assertFalse(
            os.path.exists(os.path.join(
                self.checkout, "gfx", "MShockXotto+")))

    def test_a_pack_whose_manifest_fails_is_refused(self):
        """Exact bytes, not "it looked right"."""
        self.install_pack("MShockXotto+", MSX_ID, MSX_VIEW)
        self.write_pack_manifest("MShockXotto+", corrupt=True)
        status, _, err = self.run_launch("tileset")
        self.assertEqual(status, EX_TILESET)
        self.assertIn("verification of the tileset pack", err)
        self.assertIn("FAILED", err)
        self.assertFalse(
            os.path.exists(os.path.join(
                self.checkout, "gfx", "MShockXotto+")))

    def test_a_link_inside_the_pack_is_refused_not_filtered(self):
        """It would resolve somewhere else once it landed under gfx/."""
        self.install_pack("MShockXotto+", MSX_ID, MSX_VIEW)
        os.symlink(
            "/etc/passwd",
            os.path.join(self.pack, "MShockXotto+", "sneaky.png"))
        self.write_pack_manifest("MShockXotto+")
        status, _, err = self.run_launch("tileset")
        self.assertEqual(status, EX_TILESET)
        self.assertIn("symbolic link or a special file", err)
        self.assertIn(
            "refused rather than filtered", err,
            msg=("a pack carrying one is not trustworthy at all, so "
                 "dropping the offending entry and copying the rest "
                 "would be the wrong repair"))


class TestTheStatusReport(LaunchFixture):
    """Reports only what it can observe, and changes nothing."""

    def test_status_reports_the_whole_observable_state(self):
        self.install_game()
        self.install_tileset("MShockXotto+", MSX_ID, MSX_VIEW)
        self.install_world("Sunnyside", ("#a.sav",))
        status, out, err = self.run_launch(
            "status", STUB_WINDOW_IDS="")
        self.assertEqual(status, EX_OK)
        emitted = self.emitted(out)
        self.assertEqual(emitted["PLAYTHROUGH_GAME_IS_TILES"], "1")
        self.assertEqual(emitted["PLAYTHROUGH_DISPLAY"], ":99")
        self.assertEqual(emitted["PLAYTHROUGH_DISPLAY_READY"], "1")
        self.assertEqual(
            emitted["PLAYTHROUGH_DISPLAY_GEOMETRY_OK"], "1")
        self.assertEqual(
            emitted["PLAYTHROUGH_TILESET_REQUIRED_PRESENT"], "1")
        self.assertEqual(emitted["PLAYTHROUGH_SESSION_MODE"], "resume")
        self.assertEqual(emitted["PLAYTHROUGH_GAME_RUNNING"], "0")

    def test_status_reports_a_missing_binary_as_missing(self):
        status, out, err = self.run_launch("status",
                                           STUB_WINDOW_IDS="")
        emitted = self.emitted(out)
        self.assertEqual(emitted["PLAYTHROUGH_GAME_BIN"], "")
        self.assertEqual(emitted["PLAYTHROUGH_GAME_IS_TILES"], "0")
        self.assertIn("run the 'build' subcommand", err)

    def test_status_reports_a_curses_binary_without_dying(self):
        self.install_game(version=CURSES_LINE)
        status, out, err = self.run_launch("status",
                                           STUB_WINDOW_IDS="")
        self.assertEqual(
            status, EX_OK,
            msg="status changes nothing and asserts nothing")
        self.assertEqual(
            self.emitted(out)["PLAYTHROUGH_GAME_IS_TILES"], "0")
        self.assertIn("does not report '+tiles'", err)

    def test_status_reports_a_wrong_display_without_dying(self):
        self.install_game()
        status, out, err = self.run_launch(
            "status", STUB_DIMENSIONS="1280x720", STUB_WINDOW_IDS="")
        self.assertEqual(status, EX_OK)
        emitted = self.emitted(out)
        self.assertEqual(emitted["PLAYTHROUGH_DISPLAY_READY"], "1")
        self.assertEqual(
            emitted["PLAYTHROUGH_DISPLAY_GEOMETRY_OK"], "0")

    def test_status_reports_an_absent_display(self):
        self.install_game()
        status, out, _ = self.run_launch(
            "status", STUB_XDPYINFO_RC="1", STUB_WINDOW_IDS="")
        emitted = self.emitted(out)
        self.assertEqual(emitted["PLAYTHROUGH_DISPLAY_READY"], "0")
        self.assertEqual(
            emitted["PLAYTHROUGH_DISPLAY_GEOMETRY_OK"], "0")

    def test_an_unverifiable_toolchain_is_refused_by_default(self):
        """The check the fixture declares away, asserted on its own.

        The sandbox is private, so the condition is arranged: its root
        is made world-writable, which is the state in which another
        account could replace the interpreter or a tool between the
        check and the run.  A recorded session must not run a binary it
        cannot vouch for, and this proves the refusal rather than
        trusting it.
        """
        self.install_game()
        os.chmod(self.root, 0o777)
        status, _, err = self.run_launch("headless")
        self.assertEqual(status, EX_PREREQ)
        self.assertIn("rejected as untrustworthy", err)
        self.assertIn("group- or world-writable", err)
        self.assertIn(
            "PLAYTHROUGH_ALLOW_UNVERIFIED_EXECUTABLES=1", err,
            msg=("a refusal that does not say how to proceed "
                 "deliberately is a dead end for whoever hits it"))

    def test_an_unauthenticated_display_is_refused_by_default(self):
        """A display with no cookie is a display anyone can read.

        The stub display normally refuses a client with an empty
        authority file, as an authenticated server does; here it is told
        to answer one, which is what an open display looks like.  On a
        real host that state means any local account can photograph the
        screen being captured and inject keystrokes into the session --
        both a privacy problem and a route to fabricated frames.
        """
        self.install_game()
        status, _, err = self.run_launch(
            "headless", STUB_XDPYINFO_OPEN="1")
        self.assertEqual(status, EX_DISPLAY)
        self.assertIn("no access control", err)
        self.assertIn("PLAYTHROUGH_ALLOW_UNAUTHENTICATED_X=1", err)

    def test_status_writes_nothing_into_the_checkout(self):
        self.install_game()
        self.install_tileset("ASCIITileset", ASCII_ID)
        before = sorted(os.listdir(
            os.path.join(self.checkout, "playthrough")))
        self.run_launch("status", STUB_WINDOW_IDS="")
        self.assertEqual(
            sorted(os.listdir(
                os.path.join(self.checkout, "playthrough"))),
            before)

    def test_stop_with_no_instance_is_reported_honestly(self):
        self.install_game()
        status, out, err = self.run_launch("stop", STUB_WINDOW_IDS="")
        self.assertEqual(status, EX_OK)
        self.assertEqual(
            self.emitted(out).get("PLAYTHROUGH_GAME_RUNNING"), "0")


class TestTheHeadlessSurface(LaunchFixture):
    """Delegated to env.sh, and verified."""

    def test_an_answering_display_is_accepted_as_is(self):
        status, out, err = self.run_launch("headless")
        self.assertEqual(status, EX_OK, msg=err)
        self.assertEqual(
            self.calls("Xvfb"), [],
            msg="the server is started ONLY IF the display is not "
                "already answering")

    def test_a_display_of_the_wrong_geometry_is_refused(self):
        status, _, err = self.run_launch(
            "headless", STUB_DIMENSIONS="1280x720")
        self.assertEqual(status, EX_DISPLAY)
        self.assertIn("root window is '1280x720'", err)

    def test_a_display_of_the_wrong_depth_is_refused(self):
        status, _, err = self.run_launch("headless", STUB_DEPTH="16")
        self.assertEqual(status, EX_DISPLAY)
        self.assertIn("root depth is '16'", err)


class TestTheTunableValidators(LaunchFixture):
    """The bounds are checked once, before any subcommand acts."""

    def test_an_integer_tunable_must_be_a_plain_integer(self):
        for value in ("", "4x", "-1", "1.5", " 4", "0x10"):
            with self.subTest(value=value):
                status, _, err = self.run_sourced(
                    'require_positive_int NAME "%s" 1 10' % value)
                self.assertNotEqual(status, 0)
                self.assertIn("not a plain", err)

    def test_a_zero_padded_integer_is_decimal_here(self):
        status, _, err = self.run_sourced(
            'require_positive_int NAME "08" 1 10')
        self.assertEqual(
            status, 0,
            msg="10# makes 08 decimal eight rather than a rejected "
                "octal literal")

    def test_an_integer_out_of_range_is_refused(self):
        for value in ("0", "11"):
            with self.subTest(value=value):
                status, _, err = self.run_sourced(
                    'require_positive_int NAME "%s" 1 10' % value)
                self.assertNotEqual(status, 0)
                self.assertIn("out of range", err)

    def test_a_number_tunable_accepts_a_fraction(self):
        for value in ("2", "0.5", "0.25", "10.75"):
            with self.subTest(value=value):
                status, _, _ = self.run_sourced(
                    'require_positive_number NAME "%s" 3600' % value)
                self.assertEqual(status, 0)

    def test_a_number_that_is_zero_however_spelled_is_refused(self):
        for value in ("0", "0.", "0.0", "0.00", ".0", ".00", "00"):
            with self.subTest(value=value):
                status, _, err = self.run_sourced(
                    'require_positive_number NAME "%s" 3600' % value)
                self.assertNotEqual(
                    status, 0,
                    msg=("a zero settle or timeout defeats every "
                         "bounded poll built on it"))
                self.assertIn("is zero", err)

    def test_a_number_that_is_not_a_number_is_refused(self):
        for value in ("", ".", "1.2.3", "soon", "-1", "1e3"):
            with self.subTest(value=value):
                status, _, err = self.run_sourced(
                    'require_positive_number NAME "%s" 3600' % value)
                self.assertNotEqual(status, 0)

    def test_the_job_clamp_reduces_and_reports(self):
        status, out, err = self.run_sourced(
            'BUILD_JOBS=64\nclamp_build_jobs\n'
            'printf "JOBS=%s\\n" "${BUILD_JOBS}"')
        self.assertEqual(status, 0)
        self.assertIn("JOBS=3", out)
        self.assertIn("exceeds", err)

    def test_the_job_clamp_leaves_a_safe_value_alone(self):
        status, out, err = self.run_sourced(
            'BUILD_JOBS=2\nclamp_build_jobs\n'
            'printf "JOBS=%s\\n" "${BUILD_JOBS}"')
        self.assertIn("JOBS=2", out)
        self.assertNotIn("exceeds", err)

    def test_the_compiler_major_is_read_from_the_compiler(self):
        status, out, _ = self.run_sourced("compiler_major g++-14")
        self.assertEqual(out.strip(), "14")

    def test_a_compiler_that_reports_nothing_has_no_major(self):
        status, out, _ = self.run_sourced(
            "compiler_major g++-14", STUB_COMPILER_VERSION="unknown")
        self.assertEqual(out.strip(), "")

    def test_the_tiles_predicate_reads_the_version_string(self):
        status, out, _ = self.run_sourced(
            'GAME_VERSION_ALL="%s"\nif game_is_tiles; then\n'
            '    printf "TILES=1\\n"\nelse\n    printf "TILES=0\\n"\n'
            "fi\n"
            'GAME_VERSION_ALL="%s"\nif game_is_tiles; then\n'
            '    printf "TILES=1\\n"\nelse\n    printf "TILES=0\\n"\n'
            "fi" % (VERSION_LINE, CURSES_LINE))
        self.assertEqual(out.split(), ["TILES=1", "TILES=0"])


class TestTheTrustState(LaunchFixture):
    """An instance that will be captured needs a trusted environment."""

    # env.sh's registry, which is the one list the gate consults.
    BYPASSES = (
        "PLAYTHROUGH_ALLOW_UNVERIFIED_EXECUTABLES",
        "PLAYTHROUGH_ALLOW_UNAUTHENTICATED_X",
        "PLAYTHROUGH_ALLOW_UNVERIFIED_TILESET_PACK",
        "PLAYTHROUGH_ALLOW_TILESET_FALLBACK",
        "PLAYTHROUGH_ALLOW_VULNERABLE_PILLOW",
        "PLAYTHROUGH_ALLOW_ANY_COMPILER",
    )

    def seeded(self):
        """A checkout whose options file exists, so a capture is next."""
        self.ready_to_launch()
        self.seed_config()

    def test_the_registry_is_the_one_env_sh_publishes(self):
        status, out, _ = self.run_sourced(
            'printf "%s\\n" "${PLAYTHROUGH_TRUST_BYPASS_VARS}"')
        self.assertEqual(status, EX_OK)
        self.assertEqual(
            sorted(out.split()), sorted(self.BYPASSES),
            msg=("this class asserts the gate over env.sh's own list, "
                 "so a bypass added there without a test here fails"))

    def test_every_bypass_refuses_the_capture_launch(self):
        # One sandbox for all six: each attempt is refused before
        # anything is created, so nothing accumulates between them --
        # which the frames-and-config assertion at the end proves.
        self.seeded()
        for name in self.BYPASSES:
            with self.subTest(bypass=name):
                environment = {name: "1", "STUB_WINDOW_IDS": "",
                               "PLAYTHROUGH_WINDOW_TIMEOUT": "1"}
                status, _, err = self.run_launch("launch", **environment)
                self.assertEqual(
                    status, EX_USAGE,
                    msg="%s must refuse, not warn:\n%s" % (name, err))
                self.assertIn("trust state", err)
                self.assertIn(name, err)
                self.assertNotIn(
                    "CAPTURE LAUNCH", err,
                    msg=("the refusal precedes the launch: an engine "
                         "started and then objected to has already "
                         "produced the thing being refused"))
        self.assertFalse(
            os.path.exists(os.path.join(
                self.checkout, "playthrough", "frames")),
            msg="six refusals created nothing at all")

    def test_the_refusal_names_what_the_bypass_endangers(self):
        self.seeded()
        status, _, err = self.run_launch(
            "launch", STUB_WINDOW_IDS="",
            PLAYTHROUGH_WINDOW_TIMEOUT="1",
            PLAYTHROUGH_ALLOW_TILESET_FALLBACK="1")
        self.assertEqual(status, EX_USAGE)
        self.assertIn("other than the required MSXotto+", err)
        self.assertIn("PLAYTHROUGH_CAPTURE_MODE=diagnostic", err)

    def test_a_calibration_launch_is_deliberately_exempt(self):
        """Diagnosis is separated from the record, not blocked.

        The calibration launch produces no frame -- it exists only so
        the engine writes its config tree -- and the options it leaves
        behind are verified again before the capture launch that follows.
        Refusing it would make an unverifiable host undiagnosable while
        protecting nothing.
        """
        self.ready_to_launch()
        status, _, err = self.run_launch(
            "launch", STUB_WINDOW_IDS="",
            PLAYTHROUGH_WINDOW_TIMEOUT="1",
            PLAYTHROUGH_ALLOW_TILESET_FALLBACK="1")
        self.assertIn("CALIBRATION LAUNCH", err)
        self.assertNotIn("trust state", err)

    def test_the_subcommands_that_capture_nothing_are_unaffected(self):
        self.install_game()
        self.install_tileset("MShockXotto+", MSX_ID, MSX_VIEW)
        for subcommand in ("tileset", "status", "headless"):
            with self.subTest(subcommand=subcommand):
                status, _, err = self.run_launch(
                    subcommand, STUB_WINDOW_IDS="",
                    PLAYTHROUGH_ALLOW_VULNERABLE_PILLOW="1")
                self.assertEqual(status, EX_OK, msg=err)
                self.assertNotIn("trust state", err)


class TestTheSeedingBoundary(LaunchFixture):
    """Seeding the options file is a separate, explicit step."""

    def test_the_launcher_verifies_the_options_and_never_writes_them(
            self):
        """Two halves of one boundary, and only one of them is a no.

        SEEDING stays a separate, explicit step: the engine rewrites
        options.json when it exits, so patching it from inside a launch
        would be silently discarded.  VERIFYING is not seeding, and it
        has to happen here -- the launcher is the last thing that runs
        before a session is captured, and by then the values are what
        decide whether the session is usable at all.  So the launcher
        delegates to the module that owns the contract, in --verify-only
        mode, and the file it verifies comes out byte for byte unchanged.
        """
        with open(self.script, encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("--verify-only", source)
        self.assertIn("seed_options.py", source)
        self.ready_to_launch()
        path = self.seed_config()
        with open(path, "rb") as handle:
            before = handle.read()
        status, out, err = self.run_launch(
            "launch", STUB_WINDOW_IDS="",
            PLAYTHROUGH_WINDOW_TIMEOUT="1")
        self.assertEqual(
            self.emitted(out)["PLAYTHROUGH_OPTIONS_VERIFIED"], "1",
            msg="the contract is reported as verified:\n%s" % err)
        self.assertIn("CAPTURE LAUNCH", err)
        with open(path, "rb") as handle:
            self.assertEqual(
                handle.read(), before,
                msg="verification reads; it never patches")

    def test_a_first_run_is_announced_as_a_calibration_launch(self):
        self.ready_to_launch()
        status, out, err = self.run_launch(
            "launch", STUB_WINDOW_IDS="",
            PLAYTHROUGH_WINDOW_TIMEOUT="1")
        self.assertNotEqual(
            status, EX_OK,
            msg="the stub game opens no window, so the launch fails")
        self.assertIn(
            "CALIBRATION LAUNCH", err,
            msg=("with no options.json yet, the first launch is "
                 "throwaway: it exists only so the engine writes the "
                 "config tree"))
        self.assertIn(
            "640x384", err,
            msg=("the compiled TERMINAL_X 80 / TERMINAL_Y 24 defaults "
                 "are what the first window is sized from"))
        self.assertIn("Select", err)

    def test_a_seeded_checkout_takes_the_capture_launch(self):
        self.ready_to_launch()
        self.seed_config()
        status, out, err = self.run_launch(
            "launch", STUB_WINDOW_IDS="",
            PLAYTHROUGH_WINDOW_TIMEOUT="1")
        self.assertIn(
            "CAPTURE LAUNCH", err,
            msg="the options file exists, so this launch is the one "
                "that gets captured")
        self.assertNotIn("CALIBRATION LAUNCH", err)
        self.assertIn("custom point-buy creator", err)

    def test_a_resumable_save_takes_the_capture_launch_too(self):
        self.ready_to_launch()
        self.seed_config()
        self.install_world("Sunnyside", ("#a.sav",))
        status, out, err = self.run_launch(
            "launch", STUB_WINDOW_IDS="",
            PLAYTHROUGH_WINDOW_TIMEOUT="1")
        self.assertIn(
            "CAPTURE LAUNCH (resume)", err,
            msg=("a save exists, so there is nothing to calibrate and "
                 "nothing to create: the world is loaded"))
        self.assertIn("do not create a new one", err)

    def test_a_resume_with_no_seeded_options_is_refused(self):
        """The one state that reaches a capture launch unseeded.

        A save with no options.json skips the calibration branch
        entirely -- there is nothing to calibrate and nothing to create
        -- so it used to walk straight into the captured launch with the
        engine's compiled defaults: a 12h clock, an 80x24 grid and
        whatever tileset was left.  Every count would still tally.
        """
        self.ready_to_launch()
        self.install_seeder()
        self.install_world("Sunnyside", ("#a.sav",))
        status, _, err = self.run_launch(
            "launch", STUB_WINDOW_IDS="",
            PLAYTHROUGH_WINDOW_TIMEOUT="1")
        self.assertEqual(status, EX_LAYOUT)
        self.assertIn("nothing has seeded the option values", err)
        self.assertIn("seed_options.py", err)
        self.assertNotIn("CAPTURE LAUNCH", err)

    def test_every_seeded_value_is_actually_verified(self):
        """One wrong value in eight refuses the launch.

        The defect this closes treated the EXISTENCE of options.json as
        proof that seeding had happened, so a seed that failed halfway,
        ran against another userdir, or was overwritten by an engine
        exiting afterwards reached the captured session unnoticed.  Each
        of these eight decides whether the session is usable evidence:
        the clock's width, the artwork, the grid the crop is computed
        from, the creator's point-buy tab, the audio device, and the
        character file's own name.
        """
        wrong = {
            "24_HOUR": "12h",
            "SOUND_ENABLED": "true",
            "USE_TILES": "false",
            "TILES": "UltimateCataclysm",
            "TERMINAL_X": "80",
            "TERMINAL_Y": "24",
            "CHARACTER_POINT_POOLS": "story_teller",
            "WORLD_COMPRESSION2": "true",
        }
        for name, value in wrong.items():
            with self.subTest(option=name):
                self.ready_to_launch()
                self.seed_config(**{name: value})
                status, out, err = self.run_launch(
                    "launch", STUB_WINDOW_IDS="",
                    PLAYTHROUGH_WINDOW_TIMEOUT="1")
                self.assertEqual(
                    status, EX_LAYOUT,
                    msg="%s=%s must refuse the launch:\n%s"
                        % (name, value, err))
                self.assertIn(name, err)
                self.assertIn(
                    self.emitted(out).get(
                        "PLAYTHROUGH_OPTIONS_VERIFIED"), ("0",),
                    msg="and the failure is reported as a fact too")
                self.assertNotIn(
                    "CAPTURE LAUNCH", err,
                    msg="the refusal precedes the launch entirely")

    def test_the_refusal_says_how_to_put_it_right(self):
        self.ready_to_launch()
        self.seed_config(**{"24_HOUR": "12h"})
        status, _, err = self.run_launch(
            "launch", STUB_WINDOW_IDS="",
            PLAYTHROUGH_WINDOW_TIMEOUT="1")
        self.assertEqual(status, EX_LAYOUT)
        self.assertIn("seed_options.py", err)
        self.assertIn(
            "while no engine is running", err,
            msg=("seeding underneath a live instance is discarded when "
                 "it exits, which is the mistake most likely to have "
                 "produced this state"))
        self.assertIn(
            "every duration fall to the floor", err,
            msg="the cost of ignoring this is stated, not implied")

    def test_a_missing_seeder_is_a_prerequisite_failure(self):
        """The verifier is part of the pipeline, not an optional extra."""
        self.ready_to_launch()
        self.seed_config()
        os.unlink(os.path.join(self.tooling, "seed_options.py"))
        status, _, err = self.run_launch(
            "launch", STUB_WINDOW_IDS="",
            PLAYTHROUGH_WINDOW_TIMEOUT="1")
        self.assertEqual(status, EX_PREREQ)
        self.assertIn("cannot be verified", err)
        self.assertNotIn("CAPTURE LAUNCH", err)

    def test_no_handover_without_a_confirmed_stopped_instance(self):
        # A scripted game is correctly judged not to be the game, so
        # no instance is ever confirmed -- and the launch must then
        # fail rather than reach the "seed the options now" handover.
        self.ready_to_launch()
        status, _, err = self.run_launch(
            "launch", STUB_WINDOW_IDS="4194305",
            PLAYTHROUGH_WINDOW_TIMEOUT="1")
        self.assertEqual(status, EX_WINDOW)
        self.assertIn("CALIBRATION LAUNCH", err)
        self.assertNotIn(
            "NEXT: seed the option values", err,
            msg=("a live engine rewrites options.json on exit, so the "
                 "handover is only ever reached after the calibration "
                 "instance is confirmed gone"))


class TestALiveInstance(LaunchFixture):
    """The paths that need a real, confirmable process.

    Every one of these starts a compiled fake engine from the sandbox
    checkout, so /proc/<pid>/exe, /proc/<pid>/cwd and the --userdir
    argument all match what the script requires before it will adopt or
    signal a pid.  Nothing is ever signalled by name or pattern: the
    fixture kills only the exact pid its own child recorded.
    """

    def ready_live(self):
        """A sandbox whose game is a real process."""
        self.install_live_game()
        self.install_tileset("MShockXotto+", MSX_ID, MSX_VIEW)

    def test_a_calibration_launch_ends_with_the_handover(self):
        self.ready_live()
        options = os.path.join(self.config, "options.json")
        status, out, err = self.run_launch(
            "launch", STUB_WINDOW_IDS="4194305",
            FAKE_GAME_OPTIONS=options)
        self.assertEqual(status, EX_OK, msg=err)
        self.assertIn("CALIBRATION LAUNCH", err)
        self.assertTrue(
            os.path.isfile(options),
            msg="the whole point of the throwaway launch is that the "
                "engine writes the config tree")
        self.assertIn("NEXT: seed the option values", err)
        for value in ("24_HOUR=24h", "SOUND_ENABLED=false",
                      "TILES=%s" % MSX_ID, "TERMINAL_X=240",
                      "TERMINAL_Y=67"):
            with self.subTest(value=value):
                self.assertIn(
                    value, " ".join(err.split()),
                    msg=("the handover names every value, because a "
                         "12h clock or a 640x384 window wastes a whole "
                         "captured session and the cause is invisible "
                         "at the time"))

    def test_the_calibration_instance_is_stopped_before_seeding(self):
        self.ready_live()
        options = os.path.join(self.config, "options.json")
        status, out, err = self.run_launch(
            "launch", STUB_WINDOW_IDS="4194305",
            FAKE_GAME_OPTIONS=options)
        self.assertEqual(status, EX_OK, msg=err)
        pid = self.live_pid(timeout=1.0)
        self.assertIsNotNone(pid)
        self.assertFalse(
            os.path.exists("/proc/%d" % pid),
            msg=("the engine holds its options in memory and writes "
                 "them back on exit, so it must be gone before "
                 "anything seeds the file"))
        emitted = self.emitted(out)
        self.assertEqual(emitted["PLAYTHROUGH_LAUNCH_PHASE"],
                         "calibration")
        self.assertEqual(
            emitted["PLAYTHROUGH_WINDOW_ID"], "",
            msg=("the window is gone with the instance, and reporting "
                 "a stale id would invite a caller to key into "
                 "nothing"))
        self.assertEqual(emitted["PLAYTHROUGH_GAME_PID"], "")

    def test_a_first_run_is_reported_as_a_first_run(self):
        self.ready_live()
        status, out, err = self.run_launch(
            "launch", STUB_WINDOW_IDS="4194305",
            FAKE_GAME_OPTIONS=os.path.join(self.config,
                                           "options.json"))
        self.assertEqual(
            self.emitted(out)["PLAYTHROUGH_FIRST_RUN"], "1",
            msg="a caller has to be able to tell the throwaway launch "
                "from the captured one")

    def test_a_capture_launch_confirms_the_pid_from_the_window(self):
        self.ready_live()
        self.seed_config()
        status, out, err = self.run_launch(
            "launch", STUB_WINDOW_IDS="4194305")
        self.assertEqual(status, EX_OK, msg=err)
        emitted = self.emitted(out)
        self.assertEqual(emitted["PLAYTHROUGH_FIRST_RUN"], "0")
        self.assertEqual(emitted["PLAYTHROUGH_LAUNCH_PHASE"],
                         "capture")
        self.assertEqual(emitted["PLAYTHROUGH_WINDOW_ID"], "4194305")
        self.assertEqual(emitted["PLAYTHROUGH_GAME_PID"],
                         str(self.live_pid(timeout=1.0)))
        self.assertIn("instance still alive after", err)

    def test_the_capture_launch_verifies_the_capture_surface(self):
        self.ready_live()
        self.seed_config()
        status, out, err = self.run_launch(
            "launch", STUB_WINDOW_IDS="4194305")
        self.assertEqual(status, EX_OK)
        self.assertIn("matches the 240x67 grid exactly", err)
        self.assertEqual(
            self.emitted(out)["PLAYTHROUGH_WINDOW_GEOMETRY"],
            "1920x1072+0+4")

    def test_an_unseeded_window_fails_the_capture_launch(self):
        self.ready_live()
        self.seed_config()
        status, out, err = self.run_launch(
            "launch", STUB_WINDOW_IDS="4194305",
            STUB_WINDOW_WIDTH="640", STUB_WINDOW_HEIGHT="384")
        self.assertEqual(
            status, EX_WINDOW,
            msg=("a 640x384 window means the options file was never "
                 "seeded; capturing it would produce mostly-black "
                 "frames and a sidebar crop that misses the clock"))

    def test_an_engine_that_dies_after_its_window_is_caught(self):
        self.ready_live()
        self.seed_config()
        # Alive long enough to be confirmed, gone before the settle
        # elapses -- which is the shape of a data-load abort.
        status, out, err = self.run_launch(
            "launch", STUB_WINDOW_IDS="4194305",
            FAKE_GAME_LIFETIME="2",
            PLAYTHROUGH_LIVENESS_SETTLE="6")
        self.assertEqual(status, EX_WINDOW)
        self.assertIn(
            "the engine started and then exited", err,
            msg=("a window proves only that SDL made a surface; the "
                 "content tree loads after that, so a data-load abort "
                 "must fail here rather than yield a full-length, "
                 "entirely static movie"))
        self.assertFalse(
            os.path.isfile(os.path.join(self.scratch, "game.pid")),
            msg="the pid file of a dead instance is removed")

    def test_a_window_that_vanishes_takes_its_process_with_it(self):
        # The window is there when the launch confirms it and gone by
        # the settle, while the ENGINE is still running.  That is not a
        # state to walk away from: the process holds the userdir and
        # writes its in-memory options back over a seeded options.json
        # when it eventually exits, and with nothing tracking it there
        # is nothing left to stop it.  So it is accounted for --
        # stopped, and its exit verified -- before the failure is
        # reported.
        #
        # Search calls: the idempotency probe reads one, the window
        # wait reads the one that accepts the window, so emptying the
        # search from the third makes the window vanish at exactly the
        # liveness re-check.
        self.ready_live()
        self.seed_config()
        status, _, err = self.run_launch(
            "launch", STUB_WINDOW_IDS="4194305",
            STUB_SEARCH_EMPTY_FROM="3")
        self.assertEqual(status, EX_WINDOW, msg=err)
        self.assertIn("vanished within", err)
        self.assertIn(
            "was still running and has been stopped", err,
            msg=("a window that goes without its process is the case "
                 "that orphans an engine holding the userdir"))
        self.assertFalse(
            os.path.isfile(os.path.join(self.scratch, "game.pid")),
            msg="the pid file is removed only on a confirmed death")

    def test_a_pid_read_that_fails_is_not_a_vanished_window(self):
        # The distinction the two questions have to keep: "is my window
        # still listed" is answered by the class search, which needs no
        # pid at all.  Answering it by re-resolving every match to its
        # pid meant one unreadable read was diagnosed as a vanished
        # window -- and the recovery for a vanished window is to STOP
        # the process, so a healthy engine was killed by a diagnostic.
        self.ready_live()
        self.seed_config()
        status, out, err = self.run_launch(
            "launch", STUB_WINDOW_IDS="4194305",
            STUB_WINDOW_PID_FAIL_NTH=READ_GAME_PID_CALL)
        self.assertEqual(status, EX_OK, msg=err)
        self.assertNotIn("vanished within", err)
        self.assertIn("instance still alive after", err)
        pid = self.live_pid(timeout=1.0)
        self.assertTrue(
            os.path.isdir("/proc/%d" % pid),
            msg="the engine this launch started is still running")

    def test_a_second_launch_reuses_the_first_instance(self):
        self.ready_live()
        self.seed_config()
        first = self.run_launch("launch", STUB_WINDOW_IDS="4194305")
        self.assertEqual(first[0], EX_OK, msg=first[2])
        pid = self.live_pid(timeout=1.0)
        status, out, err = self.run_launch(
            "launch", STUB_WINDOW_IDS="4194305")
        self.assertEqual(status, EX_OK, msg=err)
        self.assertIn("reusing it rather than starting a second", err)
        self.assertEqual(
            self.emitted(out)["PLAYTHROUGH_GAME_PID"], str(pid),
            msg=("two instances sharing one userdir would corrupt the "
                 "save and make the window search ambiguous"))

    def test_the_session_lock_does_not_outlive_this_shell(self):
        """A lock lives in a descriptor, and a child inherits it.

        MEASURED, NOT HYPOTHETICAL.  The session lock has to span the
        save probe and the engine start -- otherwise two runs could both
        decide to start one -- but the engine is detached and outlives
        the shell that took the lock.  With the descriptor inherited,
        the engine held the lock for its entire lifetime, and the next
        `launch` (the ordinary way a caller re-attaches to a running
        instance) blocked out its whole timeout and then reported a
        concurrent launch that did not exist.

        The assertion is deliberately about TIME as well as status: a
        second launch that succeeded only after waiting out the lock
        timeout would still be the bug.
        """
        self.ready_live()
        self.seed_config()
        first = self.run_launch("launch", STUB_WINDOW_IDS="4194305")
        self.assertEqual(first[0], EX_OK, msg=first[2])
        lock = os.path.join(self.scratch, "lock", "session.lock")
        self.assertTrue(
            os.path.isfile(lock),
            msg="the lock file is where env.sh puts it")
        started = time.monotonic()
        status, _, err = self.run_launch(
            "launch", STUB_WINDOW_IDS="4194305",
            PLAYTHROUGH_WINDOW_TIMEOUT="20")
        elapsed = time.monotonic() - started
        self.assertEqual(status, EX_OK, msg=err)
        self.assertNotIn("has held the 'session' lock", err)
        self.assertLess(
            elapsed, 15.0,
            msg=("the second launch took %.1fs, which means it waited "
                 "on a lock the first launch's engine was still "
                 "holding" % elapsed))

    def test_a_reused_instance_is_refused_under_a_trust_bypass(self):
        """Accepting an instance is starting one, for this purpose.

        The reuse branch is the one path where no launch happens in this
        run, so nothing else would ever check the environment the
        instance is about to be captured in.
        """
        self.ready_live()
        self.seed_config()
        first = self.run_launch("launch", STUB_WINDOW_IDS="4194305")
        self.assertEqual(first[0], EX_OK, msg=first[2])
        status, _, err = self.run_launch(
            "launch", STUB_WINDOW_IDS="4194305",
            PLAYTHROUGH_ALLOW_UNAUTHENTICATED_X="1")
        self.assertEqual(status, EX_USAGE)
        self.assertIn("trust state", err)
        self.assertNotIn(
            "reusing it rather than starting a second", err,
            msg="the instance is not adopted before it is refused")

    def test_a_reused_instance_is_held_to_the_same_standard(self):
        self.ready_live()
        self.seed_config()
        self.run_launch("launch", STUB_WINDOW_IDS="4194305")
        status, _, err = self.run_launch(
            "launch", STUB_WINDOW_IDS="4194305",
            STUB_WINDOW_WIDTH="640", STUB_WINDOW_HEIGHT="384")
        self.assertEqual(
            status, EX_WINDOW,
            msg=("a reused instance is the one case where no launch "
                 "happened in this run, so nothing else would ever "
                 "have checked it -- an instance that came up before "
                 "the options were seeded is exactly this"))

    def test_status_sees_a_running_instance(self):
        self.ready_live()
        self.seed_config()
        self.run_launch("launch", STUB_WINDOW_IDS="4194305")
        pid = self.live_pid(timeout=1.0)
        status, out, err = self.run_launch("status",
                                           STUB_WINDOW_IDS="4194305")
        self.assertEqual(status, EX_OK)
        emitted = self.emitted(out)
        self.assertEqual(emitted["PLAYTHROUGH_GAME_RUNNING"], "1")
        self.assertEqual(emitted["PLAYTHROUGH_GAME_PID"], str(pid))

    def test_stop_confirms_the_death_it_reports(self):
        self.ready_live()
        self.seed_config()
        self.run_launch("launch", STUB_WINDOW_IDS="4194305")
        pid = self.live_pid(timeout=1.0)
        self.assertTrue(os.path.exists("/proc/%d" % pid))
        status, out, err = self.run_launch(
            "stop", STUB_WINDOW_IDS="4194305",
            PLAYTHROUGH_STOP_TIMEOUT="5")
        self.assertEqual(status, EX_OK, msg=err)
        self.assertEqual(
            self.emitted(out)["PLAYTHROUGH_GAME_RUNNING"], "0")
        self.assertFalse(
            os.path.exists("/proc/%d" % pid),
            msg="termination is confirmed, never assumed")

    def test_stop_says_plainly_that_it_does_not_save(self):
        self.ready_live()
        self.seed_config()
        self.run_launch("launch", STUB_WINDOW_IDS="4194305")
        status, _, err = self.run_launch(
            "stop", STUB_WINDOW_IDS="4194305",
            PLAYTHROUGH_STOP_TIMEOUT="5")
        self.assertIn("WITHOUT saving", err)
        self.assertIn(
            "Save & Quit", err,
            msg=("the only exit that writes the save is the in-game "
                 "one, and a recorded session must end that way"))

    def test_the_pid_file_records_the_confirmed_pid(self):
        self.ready_live()
        self.seed_config()
        pidfile = os.path.join(self.scratch, "game.pid")
        self.run_launch("launch", STUB_WINDOW_IDS="4194305")
        with open(pidfile, encoding="utf-8") as handle:
            recorded = handle.read().strip().split()
        self.assertEqual(
            recorded[0], str(self.live_pid(timeout=1.0)),
            msg=("setsid may fork, so the spawn pid is only a "
                 "fallback: the window's _NET_WM_PID is the "
                 "authoritative source"))
        # AND THE START TIME BESIDE IT.  A bare number read back after
        # the process has gone names whatever now holds it, and the next
        # thing done with a pid from this file is a signal -- so the
        # file records the pair that a later read can re-confirm.
        self.assertEqual(
            len(recorded), 2,
            msg="the pid file is 'PID START_TIME', not a bare pid")
        self.assertRegex(recorded[1], r"^[0-9]+$")
        with open("/proc/%s/stat" % recorded[0], encoding="utf-8") as h:
            self.assertEqual(
                h.read().rsplit(") ", 1)[1].split()[19], recorded[1],
                msg="field 22 of /proc/<pid>/stat, as recorded")

    def test_a_window_owned_by_a_stranger_is_not_usable(self):
        self.ready_live()
        self.seed_config()
        status, out, err = self.run_launch(
            "launch", STUB_WINDOW_IDS="4194305",
            STUB_WINDOW_PID=str(os.getpid()),
            PLAYTHROUGH_WINDOW_TIMEOUT="1")
        self.assertEqual(
            status, EX_WINDOW,
            msg=("this very test process is not cataclysm-tiles, so "
                 "the window it supposedly owns is not this "
                 "checkout's and there is no usable instance at all"))
        self.assertIn("none belongs to this checkout", err)
        self.assertNotIn(
            "PLAYTHROUGH_GAME_PID=%d" % os.getpid(), out,
            msg=("a pipeline that adopted it would go on to signal "
                 "the tooling that started it"))

    def test_a_window_with_no_pid_at_all_is_not_usable(self):
        self.ready_live()
        self.seed_config()
        status, _, err = self.run_launch(
            "launch", STUB_WINDOW_IDS="4194305",
            STUB_WINDOW_PID_FAIL="1",
            PLAYTHROUGH_WINDOW_TIMEOUT="1")
        self.assertEqual(
            status, EX_WINDOW,
            msg=("a pid that cannot be read at all is not ours as far "
                 "as this script is concerned, which is the safe "
                 "answer: nothing is signalled and nothing is driven "
                 "on the strength of a guess"))
        self.assertIn("none belongs to this checkout", err)

    def spawn_impostor(self, binary, userdir, display=DISPLAY):
        """Start a process that looks like the game but is not ours.

        DISPLAY is passed by default and that is deliberate: the
        identity check reads it as one of its four facts, so an
        impostor started without it would be refused for the trivial
        reason that it is on no display at all -- and each test below
        would then pass without ever exercising the fact it names.
        """
        environment = {"FAKE_GAME_LIFETIME": "30", "PATH": self.bin}
        if display is not None:
            environment["DISPLAY"] = display
        process = subprocess.Popen(
            [binary, "--userdir", userdir], cwd=self.checkout,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=environment)
        self.addCleanup(self.reap, process)
        return process

    def reap(self, process):
        """Kill and WAIT, so nothing still holds the sandbox."""
        process.kill()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass

    def test_the_same_game_from_another_checkout_is_not_ours(self):
        # THE SHARPEST CASE THE IDENTITY CHECK EXISTS FOR: argv reads
        # identically, the working directory is this repository root and
        # the userdir is this pipeline's own -- only the executable
        # differs.  A pipeline that adopted it would drive, and later
        # signal, another checkout's session.
        self.ready_live()
        self.seed_config()
        elsewhere = os.path.join(self.root, "other-checkout",
                                 "cataclysm-tiles")
        os.makedirs(os.path.dirname(elsewhere))
        shutil.copyfile(self.game, elsewhere)
        os.chmod(elsewhere, 0o755)
        stranger = self.spawn_impostor(elsewhere,
                                       "./playthrough/userdir/")
        self.await_exec_of(stranger.pid, elsewhere)
        status, out, err = self.run_launch(
            "launch", STUB_WINDOW_IDS="4194305",
            STUB_WINDOW_PID=str(stranger.pid),
            PLAYTHROUGH_WINDOW_TIMEOUT="1")
        self.assertEqual(
            status, EX_WINDOW,
            msg=("/proc/<pid>/exe resolves the real binary, so a game "
                 "started from a different checkout fails there even "
                 "though its command line reads identically"))
        self.assertIn("none belongs to this checkout", err)

    def test_a_neighbouring_userdir_is_not_this_userdir(self):
        # cmdline is NUL-separated and compared element by element, so
        # `--userdir ./playthrough/userdir2/` must NOT be accepted as
        # `./playthrough/userdir/`.  A substring match would take it,
        # and this pipeline would then drive a session writing to a
        # different save.
        self.ready_live()
        self.seed_config()
        stranger = self.spawn_impostor(self.game,
                                       "./playthrough/userdir2/")
        self.await_exec(stranger.pid)
        status, out, err = self.run_launch(
            "launch", STUB_WINDOW_IDS="4194305",
            STUB_WINDOW_PID=str(stranger.pid),
            PLAYTHROUGH_WINDOW_TIMEOUT="1")
        self.assertEqual(status, EX_WINDOW)
        self.assertIn("none belongs to this checkout", err)

    def test_a_game_on_another_display_is_not_ours(self):
        # The fourth fact.  Everything else about this process matches
        # -- the same binary, the same working directory, the same
        # userdir -- and it is still not this session's game, because
        # capture photographs the X ROOT of PLAYTHROUGH_DISPLAY.  An
        # instance on another display would take the keystrokes and
        # appear in no frame at all, which is the shape of failure this
        # pipeline exists to refuse: a full-length film of a screen
        # nothing was happening on.
        self.ready_live()
        self.seed_config()
        stranger = self.spawn_impostor(self.game,
                                       "./playthrough/userdir/",
                                       display=":98")
        self.await_exec(stranger.pid)
        status, _, err = self.run_launch(
            "launch", STUB_WINDOW_IDS="4194305",
            STUB_WINDOW_PID=str(stranger.pid),
            PLAYTHROUGH_WINDOW_TIMEOUT="1")
        self.assertEqual(status, EX_WINDOW)
        self.assertIn("none belongs to this checkout", err)

    def test_two_instances_of_this_checkout_are_refused(self):
        self.ready_live()
        self.seed_config()
        first = self.run_launch("launch", STUB_WINDOW_IDS="4194305")
        self.assertEqual(first[0], EX_OK, msg=first[2])
        one = self.live_pid(timeout=1.0)
        # A second real instance of the same binary, from the same
        # working directory, against the same userdir.
        second = subprocess.Popen(
            [self.game, "--userdir", "./playthrough/userdir/"],
            cwd=self.checkout, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={"FAKE_GAME_LIFETIME": "30", "PATH": self.bin,
                 "DISPLAY": DISPLAY})
        self.addCleanup(self.reap, second)
        self.await_exec(second.pid)
        status, _, err = self.run_launch(
            "status",
            STUB_WINDOW_IDS="4194305 4194306",
            STUB_WINDOW_PIDS="4194305:%d 4194306:%d" % (one,
                                                        second.pid))
        self.assertEqual(status, EX_WINDOW)
        self.assertIn("separate instances", err)
        self.assertIn(
            "writing to the same save", err,
            msg=("keystrokes sent to the wrong one would be captured "
                 "as if they were this session"))
        self.assertNotEqual(one, second.pid)

    def test_the_userdir_argument_is_the_repository_relative_one(self):
        self.ready_live()
        self.seed_config()
        self.run_launch("launch", STUB_WINDOW_IDS="4194305")
        pid = self.live_pid(timeout=1.0)
        with open("/proc/%d/cmdline" % pid, "rb") as handle:
            argv = handle.read().split(b"\0")
        self.assertIn(b"--userdir", argv)
        self.assertIn(
            b"./playthrough/userdir/", argv,
            msg=("src/path_info.cpp:105 does not absolutise the value, "
                 "so the save lands inside the working tree only "
                 "because the launch happens from the repository "
                 "root"))

    def test_the_game_runs_from_the_repository_root(self):
        self.ready_live()
        self.seed_config()
        self.run_launch("launch", STUB_WINDOW_IDS="4194305")
        pid = self.live_pid(timeout=1.0)
        self.assertEqual(
            os.path.realpath("/proc/%d/cwd" % pid),
            os.path.realpath(self.checkout),
            msg=("data/, gfx/ and lang/mo/ are resolved relative to "
                 "the process working directory, so anywhere else is "
                 "a different game reading different assets"))

    def test_the_guard_holds_the_session_and_reports_its_end(self):
        # `guard` is the option for a caller that needs one foreground
        # process to own: it runs the same steps as `all` and then does
        # not return while the instance lives.  It must report the exit
        # rather than swallow it, so an engine that dies mid-session
        # ends the guard with a diagnosis instead of a silence.
        self.ready_live()
        self.seed_config()
        started = time.time()
        status, out, err = self.run_launch(
            "guard", STUB_WINDOW_IDS="4194305",
            FAKE_GAME_LIFETIME="3",
            PLAYTHROUGH_LIVENESS_SETTLE="0.5")
        elapsed = time.time() - started
        self.assertEqual(status, EX_OK, msg=err)
        self.assertGreaterEqual(
            elapsed, 3.0,
            msg="the guard lives exactly as long as the game does")
        self.assertIn("has exited", err)
        emitted = self.emitted(out)
        self.assertEqual(emitted["PLAYTHROUGH_GAME_RUNNING"], "0")
        self.assertIn("PLAYTHROUGH_GUARD_PID", emitted)

    def test_a_pid_confirmed_with_the_window_is_not_re_derived(self):
        # A pid read that fails AFTER the window was accepted cannot
        # un-confirm the pid.  The window is only ever accepted once
        # its owner has been verified against four /proc facts, so that
        # pid is carried forward; re-asking the window for it would
        # invent a race the launch does not have, and a transient
        # failure of the second read would then be indistinguishable
        # from a vanished window -- which is how a healthy engine gets
        # diagnosed as dead and signalled.
        self.ready_live()
        self.seed_config()
        status, out, err = self.run_launch(
            "launch", STUB_WINDOW_IDS="4194305",
            STUB_SETSID_FORKS="1",
            STUB_WINDOW_PID_FAIL_NTH=READ_GAME_PID_CALL)
        self.assertEqual(status, EX_OK, msg=err)
        self.assertEqual(
            self.emitted(out)["PLAYTHROUGH_GAME_PID"],
            str(self.live_pid(timeout=1.0)),
            msg=("the spawn pid is setsid's here, so this number can "
                 "only have come from the window's verified owner"))
        self.assertNotIn(
            "pid could not be confirmed", err,
            msg="a poisoned later read is not an unknown pid")
        self.assertIn("instance still alive after", err)

    def test_nothing_confirmable_is_reported_as_nothing(self):
        # The honesty half of the same rule: when NO source yields a
        # pid this checkout's game actually owns -- the window read
        # fails, the spawn pid belongs to nothing and the pid file
        # names a stranger -- read_game_pid reports failure and leaves
        # the pid empty.  It never falls back to a plausible number,
        # because every later step (stop, guard, status) acts on
        # whatever it holds.
        self.ready_live()
        status, out, err = self.run_sourced(
            'WINDOW_ID=4194305\n'
            'WINDOW_OWNED_PID=""\n'
            'printf "%s\\n" 999999 >"${PIDFILE}"\n'
            'if read_game_pid 999998; then\n'
            '    printf "ADOPTED=[%s]\\n" "${GAME_PID}"\n'
            'else\n'
            '    printf "REFUSED=[%s]\\n" "${GAME_PID}"\n'
            'fi\n',
            STUB_WINDOW_PID_FAIL="1")
        self.assertEqual(status, EX_OK, msg=err)
        self.assertIn(
            "REFUSED=[]", out,
            msg=("a pid that cannot be confirmed is reported as "
                 "absent, never guessed at"))

    def test_the_guard_refuses_to_watch_an_unconfirmed_pid(self):
        # Nothing here watches a process it has not identified, so a
        # guard with no confirmed pid must fail rather than sit in a
        # loop over a pid it does not have.  The rule is exercised
        # where it is decided, because a launch that reached the guard
        # has by construction confirmed a pid: the assertion is of that
        # invariant, and an invariant is only worth asserting if the
        # assertion itself is known to fire.
        status, _, err = self.run_sourced('GAME_PID=""\n'
                                          'assert_guardable\n')
        self.assertEqual(status, EX_WINDOW)
        self.assertIn("nothing to guard", err)

    def test_the_guard_watches_a_pid_that_was_confirmed(self):
        status, out, err = self.run_sourced(
            'GAME_PID=4242\n'
            'assert_guardable && printf "GUARDABLE=1\\n"\n')
        self.assertEqual(status, EX_OK, msg=err)
        self.assertIn(
            "GUARDABLE=1", out,
            msg="the refusal is about an EMPTY pid and nothing else")

    def test_the_userdir_tree_is_created_before_the_launch(self):
        self.ready_live()
        self.seed_config()
        self.run_launch("launch", STUB_WINDOW_IDS="4194305")
        for relative in ("playthrough/frames", "playthrough/build",
                         "playthrough/build/transitions",
                         "playthrough/userdir"):
            with self.subTest(path=relative):
                self.assertTrue(
                    os.path.isdir(os.path.join(self.checkout,
                                               relative)))


class TestTheSuiteTouchesNothingReal(LaunchFixture):
    """No build, no launch, no real display, no repository write."""

    def test_the_real_checkout_is_never_the_working_directory(self):
        self.install_game()
        status, out, _ = self.run_launch("build")
        self.assertEqual(status, EX_OK)
        # The payload reports the binary REPOSITORY-RELATIVE, so an
        # absolute host path cannot leak into a retained log.  The claim
        # this test makes -- that the sandbox copy is what was described
        # -- is therefore checked on the file itself: the emitted name
        # resolves against the sandbox root and exists there, and the
        # real checkout's binary was never consulted.
        reported = self.emitted(out)["PLAYTHROUGH_GAME_BIN"]
        self.assertEqual(reported, "cataclysm-tiles")
        self.assertFalse(
            os.path.isabs(reported),
            msg=("a retained diagnostic must not disclose where this "
                 "clone lives on the host"))
        self.assertTrue(
            os.path.isfile(os.path.join(self.checkout, reported)),
            msg=("env.sh resolves every path from its own location, so "
                 "the sandbox copy describes the sandbox"))

    def test_no_real_make_is_ever_invoked(self):
        self.run_launch("build")
        self.assertTrue(
            os.path.realpath(os.path.join(self.bin, "make")).startswith(
                self.root),
            msg="make on this PATH is the recording stub, not the real "
                "build system")

    def test_a_stub_replaces_a_symlink_and_never_the_host_tool(self):
        # The private PATH holds symlinks to real system tools, and
        # setsid is one of the names this fixture overrides.  Opening
        # such a name for writing would FOLLOW the link and truncate the
        # host's own binary -- so the link is removed first, and the
        # result is asserted to live inside the sandbox.
        target = shutil.which("setsid")
        self.assertIsNotNone(target)
        before = os.stat(target)
        link = os.path.join(self.bin, "setsid")
        self.assertFalse(
            os.path.islink(link),
            msg="write_stubs() already replaced the link with a stub")
        self.stub("setsid", "exit 0\n")
        after = os.stat(target)
        self.assertEqual((before.st_size, before.st_mtime),
                         (after.st_size, after.st_mtime),
                         msg="the host's setsid(1) must be untouched")
        self.assertTrue(
            os.path.realpath(link).startswith(
                os.path.realpath(self.root)))

    def test_the_repository_playthrough_tree_is_untouched(self):
        before = sorted(os.listdir(PLAYTHROUGH))
        self.install_game()
        self.install_tileset("ASCIITileset", ASCII_ID)
        self.run_launch("status", STUB_WINDOW_IDS="")
        self.assertEqual(sorted(os.listdir(PLAYTHROUGH)), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
