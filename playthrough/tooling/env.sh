#!/usr/bin/env bash
# shellcheck shell=bash
# shellcheck disable=SC2317
#
# playthrough/tooling/env.sh -- the SINGLE definition of the headless
# render environment and the artifact layout for the Cataclysm-DDA
# playthrough capture pipeline.  Every other script and module under
# playthrough/tooling/ sources this file rather than setting these
# values itself, so no two stages can drift over the display, the
# video driver or a path.
#
#     cd <repository root>
#     . playthrough/tooling/env.sh
#
# SOURCE IT FROM THE REPOSITORY ROOT.  That is a source-level
# requirement of the engine, not a style preference; the citations are
# under WORKING DIRECTORY below.  Executing the file instead prints the
# resolved contract and exports nothing, and re-sourcing is harmless.
# SOURCING CAN FAIL, AND A FAILURE IS FATAL TO THE CALLER: this file
# refuses to define a half-usable contract, so a malformed CLONE_INDEX,
# a runtime directory it cannot secure, or a video driver that is not
# x11 ends the source non-zero with a diagnosis on stderr.
#
# SDL_VIDEODRIVER IS x11 AND NEVER dummy: dummy renders zero pixels,
# which yields a black movie while every count still tallies.  The
# video driver block below is the primary defence.
#
# OUTPUT CHANNELS: sourcing is silent and every diagnostic goes to
# stderr, so stdout stays clean for the KEY=value channels the sibling
# scripts publish there.
#
# Requires bash.  BASH_SOURCE is used to locate the file, which is how
# it stays correct no matter which directory a caller sources it from.
# ---------------------------------------------------------------------
# THE SECURITY CONTRACT THIS FILE OWNS
#
# This pipeline runs unattended, on a host whose /tmp is world-writable
# WITHOUT the sticky bit (measured: mode 2777), and it produces evidence
# -- screenshots, clock readings, a save -- whose whole value is that it
# was not tampered with.  Five properties are therefore established
# here, once, so that no sibling script has to remember them:
#
#   1. ONE PRIVATE RUNTIME ROOT.  Every diagnostic, log, pid file, lock
#      and withdrawn frame lives under a 0700 directory whose type,
#      owner and mode are verified before use (playthrough_secure_dir),
#      and is created with a restrictive umask.  Nothing this pipeline
#      writes outside the working tree lands on a predictable
#      world-writable path any more.
#   2. THE DISPLAY IS AUTHENTICATED.  Xvfb is started with -auth and a
#      fresh 128-bit MIT-MAGIC-COOKIE-1, and the pipeline ASSERTS that a
#      client without the cookie is refused.  An unauthenticated X
#      server lets any local account read the screen being captured and
#      inject keystrokes into the session -- which would defeat both the
#      one-keystroke-per-frame invariant and the no-fabrication rule.
#   3. EXECUTABLES ARE VERIFIED, NOT MERELY FOUND.  Any interpreter or
#      external command this pipeline runs is checked for ownership and
#      for group- and world-writability, on the binary and on every
#      directory above it, before it is invoked
#      (playthrough_verify_executable).
#   4. PATHS ARE CONTAINED.  Artifact directories are proved to resolve
#      inside the checkout with no symlinked component
#      (playthrough_assert_inside, playthrough_assert_no_symlink), so a
#      planted symlink cannot redirect a save or a frame out of the
#      working tree.
#   5. NUMBERS FROM THE ENVIRONMENT ARE VALIDATED BEFORE ARITHMETIC.
#      bash evaluates command substitution inside an arithmetic
#      expansion, so an unvalidated timeout is code execution, not a
#      number (playthrough_validate_int).
#
# Documented escape hatches exist for diagnosis -- an unverifiable
# toolchain, an X server this pipeline did not start, a pack on an
# untrustworthy path -- and every one of them is off by default, loud
# when used, and ENFORCED rather than merely deprecated: they are
# enumerated in PLAYTHROUGH_TRUST_BYPASS_VARS below, any one of them
# being set moves PLAYTHROUGH_TRUST_STATE to "diagnostic", and a
# production launch or a production capture then REFUSES to run.  A
# warning telling an operator not to record a session is not a control;
# the state is.  See THE TRUST STATE beside playthrough_trust_refresh.
# ---------------------------------------------------------------------
# PROCESS LIFETIME -- THE HONEST CONTRACT
#
# An X server or a game started from here is detached with `setsid
# nohup ... </dev/null &`, which insulates it from signals aimed at
# this shell and lets it keep running after the calling script returns.
# That is ALL it does.  It does NOT survive teardown of the calling
# shell's whole process TREE, and no comment in this pipeline claims
# otherwise.  The full explanation, and the two honest ways to run a
# session, are at PROCESS LIFETIME beside playthrough_start_xvfb.
#
#   PLAYTHROUGH_USE_SUPERVISED_X=1   bring the display up through the
#                                    host's provisioned durable service
#                                    instead (it has no -auth; read the
#                                    warning before using it)
#   PLAYTHROUGH_REQUIRE_DURABLE_X=1  refuse to start a display whose
#                                    lifetime is this process tree, so
#                                    a run that needs durability fails
#                                    loudly instead of being promised it
#
# The three-tier preference this file actually applies -- a durable
# supervisor first, then verified detachment, then re-assertion at the
# point of use -- is documented at PROCESS LIFECYCLE below, beside the
# functions that implement it.  The practical consequence for every
# caller is one line: treat playthrough_headless_up as something to
# call again, not something that was already done.  It is idempotent
# and cheap by design.
# ---------------------------------------------------------------------
# WHY THIS FILE DOES NOT `set -euo pipefail`  (deliberate -- please do
# not "fix" it)
#
# Shell options set at the top level of a *sourced* file are imposed
# on the CALLING shell and stay there after the source returns.  A
# pipeline stage that sourced this file would silently inherit
# errexit, nounset and pipefail and change behaviour; an interactive
# shell would start exiting on the next failed command.  Every other
# *.sh in this folder is executed rather than sourced and sets those
# options itself.  This file is the one deliberate exception.  Where
# an option is genuinely needed here it is set inside a function,
# which scopes it to that function -- the same technique
# build-scripts/build.sh uses in run_test().
#
# The two shellcheck directives above are the only suppressions:
# SC2317 fires on the `return 1 2>/dev/null || exit 1` bail idiom,
# which ShellCheck cannot model because `return` succeeds when sourced
# and fails when executed, so exactly one arm runs and neither is dead
# code.
# ---------------------------------------------------------------------

# bash is required: BASH_SOURCE, arrays and `local` are all used below.
# `return` succeeds only in a sourced file, so the `||` arm covers the
# executed case.  This bail idiom has to stay at file scope: a `return`
# inside a function would only leave the function, not the file.
if [ -z "${BASH_VERSION-}" ]; then
    printf '%s\n' "playthrough/tooling/env.sh: bash is required." >&2
    return 1 2>/dev/null || exit 1
fi

# Sourced or executed?  Only used to decide whether to print the
# summary at the end; sourcing must stay silent so it cannot pollute a
# consumer's stdout.
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
    _playthrough_executed=1
else
    _playthrough_executed=0
fi

# ---------------------------------------------------------------------
# Small reporting helpers, defined first so everything below can use
# them.  playthrough_die returns 1 rather than calling exit: this file
# is sourced, and `exit` from a sourced file would kill the caller's
# shell, including an interactive one.  Consumers run with
# `set -euo pipefail`, so a non-zero return aborts them anyway.
# ---------------------------------------------------------------------
playthrough_log() {
    printf 'playthrough: %s\n' "$*" >&2
}

playthrough_warn() {
    printf 'playthrough: WARNING: %s\n' "$*" >&2
}

playthrough_die() {
    printf 'playthrough: FATAL: %s\n' "$*" >&2
    return 1
}

# ---------------------------------------------------------------------
# SECURITY PRIMITIVES
#
# Defined before anything else because the assignments further down --
# the runtime directory, the interpreter, the cookie file -- use them at
# source time.  Every one is a pure check plus, at most, one mkdir or
# one file creation; none starts a process, and none touches the working
# tree.
# ---------------------------------------------------------------------

# _playthrough_euid -- this process's effective uid, without needing a
# tool on PATH.  bash maintains EUID itself, so the ownership checks
# below keep working when this file is sourced under a PATH stripped
# down to bash; `id -u` is only the fallback for a shell that does not
# set it.
_playthrough_euid() {
    if [ -n "${EUID:-}" ]; then
        printf '%s' "${EUID}"
        return 0
    fi
    if [ -n "${UID:-}" ]; then
        printf '%s' "${UID}"
        return 0
    fi
    id -u 2>/dev/null || true
}

# The invoking user, resolved once.  Every ownership check below
# compares against this rather than shelling out again per path.
PLAYTHROUGH_UID="$(_playthrough_euid)"
export PLAYTHROUGH_UID

# playthrough_validate_int VALUE LABEL [MIN] [MAX]
#   Accept a plain decimal integer and leave it in PLAYTHROUGH_INT, or
#   refuse it.
#
#   THIS IS A SECURITY CHECK, NOT INPUT TIDINESS.  bash evaluates
#   command substitution inside an arithmetic expansion, so for a
#   timeout taken from the environment `$(( timeout * 4 ))` executes
#   whatever `$(...)` that value contains.  The `case` guard therefore
#   runs FIRST and rejects anything that is not digits, and only then is
#   the value converted -- with 10#, so that a zero-padded "007" is
#   seven and not an octal parse error.
playthrough_validate_int() {
    PLAYTHROUGH_INT=""
    local raw="${1-}"
    local label="${2:-value}"
    local min="${3:-0}"
    local max="${4:-2147483647}"
    case "${raw}" in
        ''|*[!0-9]*)
            playthrough_die "${label}='${raw}' is not a plain" \
                "non-negative decimal integer.  It is refused before" \
                "any arithmetic touches it: bash evaluates command" \
                "substitution inside an arithmetic expansion, so such" \
                "a value would be executed rather than counted."
            return 1
            ;;
    esac
    local value
    value=$(( 10#${raw} ))
    if [ "${value}" -lt "${min}" ] || [ "${value}" -gt "${max}" ]; then
        playthrough_die "${label}=${value} is outside" \
            "${min}..${max}"
        return 1
    fi
    PLAYTHROUGH_INT="${value}"
    return 0
}

# playthrough_secure_dir PATH [MODE] [LABEL]
#   Create or adopt a private directory, proving it is ours first.
#
#   The checks are ordered so that nothing is trusted: a symlink is
#   refused outright (it is the classic redirect), the path must be a
#   real directory AFTER the creation as well as before it -- a race
#   that replaced the name in between is caught by the second test --
#   and its owner must be this user, which is what stops an attacker who
#   pre-created the predictable name from owning the pipeline's runtime
#   state.  Creation happens under umask 077 so the directory is never
#   briefly world-readable, and the mode is CONFIRMED after the chmod
#   rather than assumed from its exit status.
#
#   LABEL is what the diagnostics call the directory; it defaults to the
#   path itself.  This is the ONLY way anything in this tree brings a
#   scratch directory into existence.
#
#   `stat` IS THE CHECK, so its absence is reported as an inability to
#   verify rather than as a failed verification: this file is SOURCED by
#   every stage, including on a PATH stripped to bash itself, and dying
#   there would make the whole contract unavailable on a host where
#   nothing is actually wrong.  coreutils ships stat on every platform
#   this pipeline targets, so the warning is a diagnostic for a broken
#   PATH and not a supported mode of operation.
playthrough_secure_dir() {
    local path="${1-}"
    local mode="${2:-700}"
    local label="${3:-${1-}}"
    local owner uid kind actual
    if [ -z "${path}" ]; then
        playthrough_die "playthrough_secure_dir needs a path"
        return 1
    fi
    if [ -L "${path}" ]; then
        playthrough_die "${label} '${path}' is a symbolic link;" \
            "refusing to use it as a private runtime directory," \
            "because that is exactly how a shared temporary path is" \
            "turned into a write somewhere else"
        return 1
    fi
    if [ ! -e "${path}" ]; then
        if ! ( umask 077 && mkdir -p -- "${path}" ); then
            playthrough_die "cannot create ${label} '${path}'"
            return 1
        fi
    fi
    if [ ! -d "${path}" ]; then
        playthrough_die "${label} '${path}' exists and is not a" \
            "directory"
        return 1
    fi
    if ! command -v stat >/dev/null 2>&1; then
        chmod "${mode}" -- "${path}" 2>/dev/null || true
        playthrough_warn "stat is not on PATH (coreutils), so" \
            "${label} '${path}' could not be verified as a" \
            "mode-${mode} directory owned by this user.  Install" \
            "coreutils before capturing a session."
        return 0
    fi
    # Re-tested after the creation: a race that swapped the name between
    # the check above and the mkdir is caught here.
    kind="$(stat -Lc '%F' -- "${path}" 2>/dev/null || true)"
    if [ -L "${path}" ] || [ "${kind}" != "directory" ]; then
        playthrough_die "${label} '${path}' is a" \
            "${kind:-unreadable path}, not a real directory"
        return 1
    fi
    uid="${PLAYTHROUGH_UID:-$(_playthrough_euid)}"
    owner="$(stat -Lc '%u' -- "${path}" 2>/dev/null || true)"
    if [ "${owner}" != "${uid}" ]; then
        playthrough_die "${label} '${path}' is owned by uid" \
            "'${owner:-unknown}', not by uid ${uid}; refusing to" \
            "write the pipeline's runtime state into a directory" \
            "this user does not own"
        return 1
    fi
    # The mode BEFORE the chmod, so that a repair can be announced.  A
    # directory found at the mode it should already have is the normal
    # case and says nothing -- sourcing this file has to stay silent --
    # but one found wider is a different matter: something else opened
    # the pipeline's private runtime state to other accounts, and the
    # repair is the only moment anyone would ever learn that happened.
    # Fixing it quietly would leave the operator believing it had always
    # been 0700.
    local previous
    previous="$(stat -Lc '%a' -- "${path}" 2>/dev/null || true)"
    if ! chmod "${mode}" -- "${path}"; then
        playthrough_die "cannot chmod ${mode} ${label} '${path}'"
        return 1
    fi
    actual="$(stat -Lc '%a' -- "${path}" 2>/dev/null || true)"
    if [ "${actual}" != "${mode}" ]; then
        playthrough_die "${label} '${path}' is mode" \
            "'${actual:-unknown}' after chmod ${mode}, not ${mode}"
        return 1
    fi
    if [ -n "${previous}" ] && [ "${previous}" != "${mode}" ]; then
        playthrough_warn "${label} '${path}' was mode" \
            "${previous}, not ${mode}; it has been repaired to" \
            "${mode}, but something outside this pipeline widened it," \
            "and anything written there while it was open was" \
            "readable by other accounts on this host"
    fi
    return 0
}

# playthrough_secure_file PATH [MODE_OR_LABEL]
#   Ensure PATH is a regular file this user owns, creating it empty and
#   private if it is absent.  Existing content is preserved -- this is
#   the append-safe form; playthrough_secure_truncate is the other one.
#
#   THIS IS THE ONLY SANCTIONED WAY anything in this tree opens a
#   scratch file for writing, and it is a security control rather than a
#   convenience.  A plain `>"${SOME_LOG}"` on a predictable path is a
#   hole: another account -- or an earlier, differently-configured run
#   -- can leave a symlink at that name, and the redirection then
#   truncates and overwrites whatever it points at, with this process's
#   privileges.  So:
#
#     * the containing directory is held to playthrough_secure_dir, so
#       it is a real mode-0700 directory owned by this user;
#     * a symlink at PATH is refused, never followed;
#     * an absent file is created EXCLUSIVELY -- `set -o noclobber` uses
#       O_CREAT|O_EXCL, which fails with EEXIST even for a symlink whose
#       target does not exist, so a dangling link cannot be followed
#       either -- and the name is re-tested for a link afterwards;
#     * an existing file must be a regular file owned by this user.
#
#   The second argument is a MODE when it is all digits and a LABEL for
#   the diagnostics otherwise, which is what lets a caller say either
#   `playthrough_secure_file "$log" 600` or
#   `playthrough_secure_file "$log" "the build log"`.
playthrough_secure_file() {
    local path="${1-}"
    local mode="600"
    local label="${1-}"
    case "${2-}" in
        '') ;;
        *[!0-9]*) label="${2}" ;;
        *) mode="${2}" ;;
    esac
    local dir owner uid kind
    if [ -z "${path}" ]; then
        playthrough_die "playthrough_secure_file needs a path"
        return 1
    fi
    dir="$(dirname -- "${path}")"
    playthrough_secure_dir "${dir}" 700 \
        "the directory for ${label}" || return 1
    if [ -L "${path}" ]; then
        playthrough_die "${label} '${path}' is a symbolic link;" \
            "refusing to write through it.  Delete it and re-run."
        return 1
    fi
    if [ ! -e "${path}" ]; then
        # O_CREAT|O_EXCL via noclobber, in a subshell under umask 077 so
        # neither the option nor the mask leaks into the caller's shell.
        if ! ( umask 077; set -o noclobber; : >"${path}" ) 2>/dev/null
        then
            playthrough_die "could not exclusively create ${label}" \
                "'${path}'; something created it underneath this" \
                "check, which is exactly the race this guard exists" \
                "to refuse"
            return 1
        fi
    fi
    # Re-test for a link after the creation.
    if [ -L "${path}" ]; then
        playthrough_die "${label} '${path}' became a symbolic link" \
            "while it was being created; refusing to write to it"
        return 1
    fi
    if command -v stat >/dev/null 2>&1; then
        kind="$(stat -Lc '%F' -- "${path}" 2>/dev/null || true)"
        case "${kind}" in
            "regular file"|"regular empty file") ;;
            *)
                playthrough_die "${label} '${path}' is a" \
                    "${kind:-unreadable path}, not a regular file"
                return 1
                ;;
        esac
        uid="${PLAYTHROUGH_UID:-$(_playthrough_euid)}"
        owner="$(stat -Lc '%u' -- "${path}" 2>/dev/null || true)"
        if [ "${owner}" != "${uid}" ]; then
            playthrough_die "${label} '${path}' is owned by uid" \
                "'${owner:-unknown}', not by uid ${uid}"
            return 1
        fi
    elif [ ! -f "${path}" ]; then
        playthrough_die "${label} '${path}' is not a regular file"
        return 1
    fi
    if ! chmod "${mode}" -- "${path}"; then
        playthrough_die "cannot chmod ${mode} ${label} '${path}'"
        return 1
    fi
    return 0
}

# playthrough_secure_truncate PATH [MODE_OR_LABEL]
#   playthrough_secure_file, then empty the file.  Used for logs and pid
#   files that a new run starts afresh; every other caller wants the
#   append-safe form above.
playthrough_secure_truncate() {
    local path="${1-}"
    playthrough_secure_file "${path}" "${2-}" || return 1
    if ! : >"${path}"; then
        playthrough_die "cannot truncate ${path}"
        return 1
    fi
    return 0
}

# playthrough_verify_executable PATH LABEL
#   Prove that an executable is one an unattended pipeline may run.
#
#   Finding a command is not the same as trusting it.  The value may
#   come from the environment (PLAYTHROUGH_PYTHON, PLAYTHROUGH_COMPILER)
#   or from a PATH this process does not control, so the file and every
#   directory above it are checked: the target must be a regular
#   executable file, and neither it nor any ancestor may be group- or
#   world-writable or owned by anyone other than root or this user.  A
#   writable ancestor is enough on its own -- it lets the binary be
#   replaced between this check and the next run.
#
#   Symlinks are followed for the CHECK and never for the CALL: the
#   caller keeps invoking the name it resolved, because ImageMagick
#   dispatches on argv[0] (/usr/bin/convert is a symlink to magick here,
#   and calling the target directly would change its behaviour).
#
#   Reports on stderr and returns non-zero; the caller decides whether
#   that is fatal, because the answer differs between the interpreter
#   (fatal) and an optional tool (a missing-tool message).
playthrough_verify_executable() {
    local path="${1-}"
    local label="${2:-executable}"
    if [ -z "${path}" ]; then
        playthrough_warn "no path given for ${label}"
        return 1
    fi
    local real
    real="$(readlink -f -- "${path}" 2>/dev/null || true)"
    if [ -z "${real}" ] || [ ! -f "${real}" ] || [ ! -x "${real}" ]; then
        playthrough_warn "${label} '${path}' is not an executable" \
            "regular file"
        return 1
    fi
    # `stat` IS THE CHECK, and its absence is an inability to verify
    # rather than a failed verification.  This file is SOURCED by every
    # stage, including on a PATH stripped down to bash itself, and
    # refusing there would make the whole contract unavailable on a host
    # where nothing is wrong -- the same rule playthrough_secure_dir
    # applies, for the same reason.  coreutils ships stat everywhere
    # this pipeline runs, so the warning is a diagnostic for a broken
    # PATH and never a supported mode of operation.
    if ! command -v stat >/dev/null 2>&1; then
        playthrough_warn "stat is not on PATH (coreutils), so" \
            "${label} '${path}' could not be checked for third-party" \
            "ownership or group- and world-writability.  Install" \
            "coreutils before capturing a session."
        return 0
    fi
    local entry="${real}"
    local perm owner
    while : ; do
        perm="$(stat -c '%a' -- "${entry}" 2>/dev/null || true)"
        owner="$(stat -c '%u' -- "${entry}" 2>/dev/null || true)"
        if [ -z "${perm}" ] || [ -z "${owner}" ]; then
            playthrough_warn "cannot stat '${entry}' while verifying" \
                "${label}"
            return 1
        fi
        if [ "${owner}" != "0" ] &&
           [ "${owner}" != "${PLAYTHROUGH_UID}" ]; then
            playthrough_warn "${label} '${path}': '${entry}' is" \
                "owned by uid ${owner}, which is neither root nor" \
                "uid ${PLAYTHROUGH_UID}"
            return 1
        fi
        if [ $(( 8#${perm} & 8#022 )) -ne 0 ]; then
            playthrough_warn "${label} '${path}': '${entry}' is" \
                "mode ${perm}, i.e. group- or world-writable, so it" \
                "can be replaced by another account between this" \
                "check and the next invocation"
            return 1
        fi
        [ "${entry}" = "/" ] && break
        entry="${entry%/*}"
        [ -n "${entry}" ] || entry="/"
    done
    return 0
}

# playthrough_assert_inside PATH ROOT LABEL
#   Refuse a path that does not resolve inside ROOT.  readlink -m
#   resolves every existing component, so neither a `..` segment nor a
#   symlink can smuggle a destination past this.
playthrough_assert_inside() {
    local path="${1-}"
    local root="${2-}"
    local label="${3:-path}"
    local real_path real_root
    real_path="$(readlink -m -- "${path}" 2>/dev/null || true)"
    real_root="$(readlink -m -- "${root}" 2>/dev/null || true)"
    if [ -z "${real_path}" ] || [ -z "${real_root}" ]; then
        playthrough_die "cannot resolve ${label} '${path}' against" \
            "'${root}'"
        return 1
    fi
    case "${real_path}" in
        "${real_root}"|"${real_root}"/*) return 0 ;;
    esac
    playthrough_die "${label} '${path}' resolves to '${real_path}'," \
        "which is outside '${real_root}'.  Every artifact of this" \
        "pipeline is written inside the checkout, so a destination" \
        "outside it is refused rather than followed."
    return 1
}

# playthrough_assert_no_symlink PATH ROOT LABEL
#   Walk every component of PATH below ROOT and refuse any that is a
#   symbolic link.  Containment alone is not enough: a symlink that
#   points back inside the tree would pass it, and the invariant this
#   pipeline needs is that frames, the build directory and the userdir
#   are real directories nobody has redirected.
playthrough_assert_no_symlink() {
    local path="${1-}"
    local root="${2-}"
    local label="${3:-path}"
    case "${path}" in
        "${root}"/*) ;;
        *)
            playthrough_die "${label} '${path}' is not written" \
                "beneath '${root}'"
            return 1
            ;;
    esac
    local rest="${path#"${root}"/}"
    local prefix="${root}"
    local component
    while [ -n "${rest}" ]; do
        component="${rest%%/*}"
        if [ "${component}" = "${rest}" ]; then
            rest=""
        else
            rest="${rest#*/}"
        fi
        [ -n "${component}" ] || continue
        prefix="${prefix}/${component}"
        if [ -L "${prefix}" ]; then
            playthrough_die "${label} '${path}' has a symlinked" \
                "component at '${prefix}'.  A link there can" \
                "redirect a save file or a captured frame out of the" \
                "working tree, so it is refused rather than" \
                "followed."
            return 1
        fi
    done
    return 0
}

# ---------------------------------------------------------------------
# WORKING DIRECTORY: why every command in this pipeline runs from the
# repository root
#
# This is enforced by the engine's own path handling, not by taste:
#
#   * --userdir is normalised but NOT absolutised --
#     src/path_info.cpp:105 `user_dir_value = as_norm_dir( dir );` --
#     so `--userdir ./playthrough/userdir/` resolves against the
#     process working directory.
#   * With an empty --basepath the asset roots are likewise working
#     directory relative: src/path_info.cpp:129
#     `datadir_value = "data/";`, :134 `gfxdir_value = prefix +
#     "gfx/";`, :136 `langdir_value = prefix + "lang/mo/";`.
#
# The repository root is therefore the ONLY working directory under
# which this checkout's own data/, gfx/ and lang/mo/ resolve AND the
# userdir lands inside the working tree where git can track it.  Any
# other choice breaks both halves at once -- which is why the paths
# below are resolved absolutely from BASH_SOURCE and exported, so no
# sibling has to guess.
#
# The root-resolution idiom is the repository's own, from
# build-scripts/clang-tidy-run.sh:8-9, adjusted for this file's depth
# of two directories rather than one.
# ---------------------------------------------------------------------
_playthrough_script_dir="$(
    cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd
)"
if [ -z "${_playthrough_script_dir}" ]; then
    playthrough_die "cannot resolve the directory of env.sh"
    return 1 2>/dev/null || exit 1
fi

_playthrough_repo_root="$(
    cd "${_playthrough_script_dir}/../.." >/dev/null 2>&1 && pwd
)"
if [ -z "${_playthrough_repo_root}" ]; then
    playthrough_die "cannot resolve the repository root from" \
        "${_playthrough_script_dir}"
    return 1 2>/dev/null || exit 1
fi

# Fail loudly if this file has been copied somewhere that is not a
# Cataclysm-DDA checkout.  Every stage below is meaningless without
# the engine's data tree, and a wrong root would otherwise surface
# much later as an unexplained black frame or an empty save.
if [ ! -d "${_playthrough_repo_root}/data" ] ||
   [ ! -f "${_playthrough_repo_root}/src/path_info.cpp" ]; then
    playthrough_die "'${_playthrough_repo_root}' is not a" \
        "Cataclysm-DDA checkout (no data/ or src/path_info.cpp)"
    return 1 2>/dev/null || exit 1
fi

# ---------------------------------------------------------------------
# Display and runtime directory
#
# The canonical contract is DISPLAY=:99 on an X server started as
# `Xvfb :99 -screen 0 1920x1080x24`, with openbox as a minimal window
# manager so that focus and keyboard delivery behave (xdotool key
# delivery is unreliable on a bare X server with no WM).
#
# CLONE_INDEX offsets the display and the runtime directory so that
# two checkouts on one host cannot fight over a single X server or
# capture each other's windows.  It is normalised with 10# so that a
# zero-padded value such as "000" is read as decimal zero rather than
# as octal.  Index N yields DISPLAY=:(99 + N) and
# XDG_RUNTIME_DIR=/tmp/xdg<N>, so index 0 -- unset, "0" and "000"
# alike -- yields exactly DISPLAY=:99 and XDG_RUNTIME_DIR=/tmp/xdg
# with no suffix at all, the canonical single-checkout contract.
# Every log, pid file and scratch path this file exports then lives
# inside that directory, which is why they need no suffix of their own.
#
# AN ABSENT INDEX MEANS ZERO.  AN EXPLICIT BAD INDEX IS REFUSED.
# The distinction is the whole point of this block and it is not
# pedantry.  A caller who set nothing is asking for the canonical
# single-checkout contract, and giving it to them is correct.  A
# caller who set CLONE_INDEX at all is telling us they are running
# more than one checkout on this host -- so coercing a value we could
# not read down to 0 would route that clone onto the CANONICAL
# DISPLAY=:99 and the UNSUFFIXED /tmp paths, i.e. straight into the
# resources of the clone that legitimately holds index 0.  The
# symptoms are two engines keying each other's windows, two capturers
# photographing one screen, and one clone's frames landing in another
# clone's session -- a run that would continue and produce a
# plausible-looking movie of somebody else's session.  Every one of
# those corrupts the 1:1 keystroke-to-frame relation invisibly, so the
# value is validated BEFORE any shared resource path is derived from
# it, and a value that cannot be believed stops this file rather than
# being guessed at.
#
# The upper bound exists for the same reason rather than as taste:
# the index becomes an X display number (:99 + index), and X display
# numbers are small non-negative integers.  A four-digit index would
# name a display no Xvfb in this pipeline will ever serve, and the
# failure would surface much later as an unexplained "no X server"
# instead of here, at the line that could name the cause.
# ---------------------------------------------------------------------
PLAYTHROUGH_MAX_CLONE_INDEX=99
export PLAYTHROUGH_MAX_CLONE_INDEX

# The display number clone 0 uses, named once so the failure message
# below and the export beneath it cannot disagree about it.
_playthrough_display_base=99

if [ -z "${CLONE_INDEX+set}" ]; then
    # Genuinely unset: the canonical single-checkout contract.
    _playthrough_index=0
else
    _playthrough_index_raw="${CLONE_INDEX}"
    case "${_playthrough_index_raw}" in
        ""|*[^0-9]*)
            playthrough_die "CLONE_INDEX is" \
                "'${_playthrough_index_raw}', which is not a decimal" \
                "non-negative integer.  It is refused rather than" \
                "coerced to 0, because 0 owns the canonical" \
                "DISPLAY=:99 and the unsuffixed /tmp paths: a clone" \
                "silently routed there would fight the clone that" \
                "really is index 0 over one X server.  Unset" \
                "CLONE_INDEX for a single-checkout run, or set it to" \
                "an integer from 0 to ${PLAYTHROUGH_MAX_CLONE_INDEX}."
            return 1 2>/dev/null || exit 1
            ;;
    esac
    _playthrough_index=$(( 10#${_playthrough_index_raw} ))
    if [ "${_playthrough_index}" -gt \
         "${PLAYTHROUGH_MAX_CLONE_INDEX}" ]; then
        playthrough_die "CLONE_INDEX is" \
            "'${_playthrough_index_raw}' (${_playthrough_index})," \
            "above the maximum of ${PLAYTHROUGH_MAX_CLONE_INDEX}." \
            "The index becomes the X display number" \
            "$(( 99 + _playthrough_index )), and no server in this" \
            "pipeline is started there.  It is refused rather than" \
            "clamped, because a clamped index would collide with" \
            "whichever clone genuinely holds the clamped value."
        return 1 2>/dev/null || exit 1
    fi
fi

export PLAYTHROUGH_CLONE_INDEX="${_playthrough_index}"
export PLAYTHROUGH_DISPLAY_NUM=$((
    _playthrough_display_base + _playthrough_index ))
export PLAYTHROUGH_DISPLAY=":${PLAYTHROUGH_DISPLAY_NUM}"
export DISPLAY="${PLAYTHROUGH_DISPLAY}"

# A suffix for host-global scratch paths, empty at index 0 so the
# canonical run uses the plain names.
if [ "${_playthrough_index}" -eq 0 ]; then
    _playthrough_suffix=""
else
    _playthrough_suffix="${_playthrough_index}"
fi

# XDG_RUNTIME_DIR must exist at mode 0700 before it is exported: SDL,
# Mesa and dbus all refuse or warn on a world-readable runtime
# directory, and a missing one produces a confusing SDL init failure.
#
# IT IS ALSO VERIFIED, NOT MERELY CREATED.  The name is predictable and
# /tmp on this class of host is world-writable WITHOUT the sticky bit
# (measured: mode 2777), so `mkdir -p` alone is not enough: another
# account can pre-create the name -- as itself, or as a symlink pointing
# anywhere -- and then read or redirect everything the pipeline writes
# underneath.  playthrough_secure_dir refuses a link, refuses a
# non-directory, refuses a directory this user does not own, and
# confirms the mode rather than trusting chmod, which turns a silent
# redirect into a loud failure.
_playthrough_runtime_dir="/tmp/xdg${_playthrough_suffix}"
if ! playthrough_secure_dir "${_playthrough_runtime_dir}" 700 \
        "XDG_RUNTIME_DIR"; then
    return 1 2>/dev/null || exit 1
fi
export XDG_RUNTIME_DIR="${_playthrough_runtime_dir}"

# ---------------------------------------------------------------------
# The private runtime root: one place for everything this pipeline
# writes OUTSIDE the working tree
#
# Logs, pid files, lock files, the X authority cookie and any withdrawn
# frame live here, under a directory whose type, owner and mode have
# been verified.  Three reasons it is not /tmp/<name> any more:
#
#   * a predictable path in a world-writable directory can be
#     pre-created or symlinked by any local account, which redirects or
#     clobbers whatever is written through it;
#   * a rejected screenshot is a full-resolution capture of the session
#     -- evidence, and nobody else's business -- so it must not be
#     world-readable, which a file created under the default umask in a
#     0755 directory is;
#   * the X cookie below is a credential, and a credential in a shared
#     directory is not a credential.
#
# These paths are deliberately NOT inside playthrough/: the terminal
# `!/playthrough/**` negation in .gitignore would make diagnostics
# committable, and they are diagnostics, not artifacts.
#
# A caller may NOMINATE the root with PLAYTHROUGH_RUNTIME_DIR -- a
# sandbox, or a host that keeps its per-user runtime state elsewhere.
# What it may not do is escape the guarantee: whatever is nominated goes
# through exactly the same check as the default, so it is still a real
# directory, still owned by this user, still mode 0700 and still never a
# symlink, and so are the four subdirectories below it.  The control is
# that the runtime root is VERIFIED, not that it is hard-coded.
# ---------------------------------------------------------------------
_playthrough_scratch_dir="${PLAYTHROUGH_RUNTIME_DIR:-\
${XDG_RUNTIME_DIR}/playthrough}"
export PLAYTHROUGH_RUNTIME_DIR="${_playthrough_scratch_dir}"
export PLAYTHROUGH_LOG_DIR="${PLAYTHROUGH_RUNTIME_DIR}/log"
export PLAYTHROUGH_RUN_DIR="${PLAYTHROUGH_RUNTIME_DIR}/run"
export PLAYTHROUGH_LOCK_DIR="${PLAYTHROUGH_RUNTIME_DIR}/lock"
export PLAYTHROUGH_REJECT_DIR="${PLAYTHROUGH_RUNTIME_DIR}/rejected"
for _playthrough_dir in \
    "${PLAYTHROUGH_RUNTIME_DIR}" \
    "${PLAYTHROUGH_LOG_DIR}" \
    "${PLAYTHROUGH_RUN_DIR}" \
    "${PLAYTHROUGH_LOCK_DIR}" \
    "${PLAYTHROUGH_REJECT_DIR}"; do
    if ! playthrough_secure_dir "${_playthrough_dir}" 700 \
            "the pipeline runtime directory"; then
        unset _playthrough_dir
        return 1 2>/dev/null || exit 1
    fi
done
unset _playthrough_dir

# ---------------------------------------------------------------------
# THE RENDERING CONTRACT -- READ THIS BEFORE TOUCHING EITHER DRIVER
#
# Two variables below take a value spelled "dummy" and only ONE of
# them ever may:
#
#   SDL_AUDIODRIVER=dummy    CORRECT and required.  A headless host
#                            has no audio device, and the game is run
#                            with SOUND_ENABLED=false, so the null
#                            audio backend is exactly right.  Without
#                            it SDL_mixer spends the session retrying
#                            a device that will never appear.
#
#   SDL_VIDEODRIVER=dummy    CATASTROPHIC, and BANNED everywhere in
#                            this tree including as any script's
#                            default.  The dummy video backend
#                            renders zero pixels.  The game still
#                            runs, every keystroke still lands,
#                            `import -window root` still writes a
#                            PNG, ffmpeg still encodes, and every
#                            acceptance count still matches -- the
#                            only symptom is that the finished movie
#                            shows nothing at all.  It is the one
#                            completely silent failure mode of this
#                            pipeline, and the closest thing to
#                            accidental fabrication it can suffer.
#
# SDL_VIDEODRIVER is therefore exported UNCONDITIONALLY.  It is
# deliberately NOT written as "${SDL_VIDEODRIVER:-x11}": that is a
# default, and a caller who already had dummy in their environment
# would silently win.  This file overwrites it instead, and then
# asserts the result.
#
# Calibration measured on this host with
#     convert <png> -colorspace Gray \
#         -format "%[fx:mean] %[fx:standard_deviation]" info:
#     real rendered frame     mean=0.270018   std=0.198145
#     dummy video driver      mean=0          std=0
#     uniform solid colour    mean>0          std=0
# verify_artifacts.sh asserts mean > 0 AND std > 0 as the backstop.
# This file is the primary defence.
# ---------------------------------------------------------------------
export SDL_VIDEODRIVER=x11
export SDL_AUDIODRIVER=dummy

# No GPU exists on a headless host, so force the software rasteriser
# (llvmpipe).  Without this, GL initialisation can fail outright or
# fall back inconsistently between launches.
export LIBGL_ALWAYS_SOFTWARE=1

# ---------------------------------------------------------------------
# PYTHONDONTWRITEBYTECODE=1 is load-bearing, not hygiene
#
# .gitignore:161 is `__pycache__` and :162 is `*.pyc`, both
# unanchored.  git applies the LAST matching pattern, and the terminal
# negation block ends with `!/playthrough/**` (.gitignore:275), which
# therefore RE-INCLUDES playthrough/tooling/__pycache__/*.pyc.
# Verified in this checkout: `git check-ignore -v` on a real .pyc
# under playthrough/tooling/ answers with the negation line, and
# `git add --dry-run` prints `add '...cpython-312.pyc'`.
#
# That negation has to stay last for the save data to be tracked at
# all, so a re-exclusion cannot simply be appended after it.
# Bytecode is prevented at source instead.  commit_artifacts.sh is the
# second line of defence: it stages the artifact classes explicitly
# rather than blanket-adding the tree.
#
# For the same reason a virtualenv must NEVER be created underneath
# playthrough/ -- the negation would re-include every byte of it.
# Keep interpreters out of tree; see PLAYTHROUGH_PYTHON below.
# ---------------------------------------------------------------------
export PYTHONDONTWRITEBYTECODE=1

# Line-buffer Python's stdout/stderr so that a long capture session
# reports progress as it happens instead of at exit.
export PYTHONUNBUFFERED=1

# ---------------------------------------------------------------------
# Artifact layout -- one authoritative definition for every sibling
#
# Absolute paths, so a consumer is correct even if it is invoked from
# elsewhere; plus the two repository-root-relative forms that are
# passed to the game on the command line, which MUST stay relative
# for the reasons given under WORKING DIRECTORY above.
# ---------------------------------------------------------------------
export PLAYTHROUGH_REPO_ROOT="${_playthrough_repo_root}"
export PLAYTHROUGH_DIR="${_playthrough_repo_root}/playthrough"
export PLAYTHROUGH_TOOLING_DIR="${PLAYTHROUGH_DIR}/tooling"
export PLAYTHROUGH_FRAMES_DIR="${PLAYTHROUGH_DIR}/frames"
export PLAYTHROUGH_BUILD_DIR="${PLAYTHROUGH_DIR}/build"
export PLAYTHROUGH_TRANSITIONS_DIR="${PLAYTHROUGH_BUILD_DIR}/transitions"
export PLAYTHROUGH_USERDIR="${PLAYTHROUGH_DIR}/userdir"

# Engine-managed subtrees of the userdir.  src/path_info.cpp:144
# `savedir_value = user_dir_value + "save/";`, :164
# `config_dir_value = user_dir_value + "config/";`, :167
# `options_value = config_dir_value + "options.json";`.  The user
# keybinding overrides live beside them (src/path_info.cpp:400-402) and
# are committed so the captured state is auditable: the committed file
# shows whether a debug action is bound in it, which is a statement
# about that file and not a history of the session.  The complementary
# evidence is source-level -- data/raw/keybindings.json declares
# `debug_mode` (3398-3403), `debug` (3404-3409) and `debug_hour_timer`
# (3466-3471) with no `bindings` array at all, so they are unbound by
# default and unreachable unless something binds them here.
export PLAYTHROUGH_SAVE_DIR="${PLAYTHROUGH_USERDIR}/save"
export PLAYTHROUGH_CONFIG_DIR="${PLAYTHROUGH_USERDIR}/config"
export PLAYTHROUGH_OPTIONS_JSON="${PLAYTHROUGH_CONFIG_DIR}/options.json"
_playthrough_kbjson="${PLAYTHROUGH_CONFIG_DIR}/keybindings.json"
export PLAYTHROUGH_KEYBINDINGS_JSON="${_playthrough_kbjson}"

# Data and media artifacts.
export PLAYTHROUGH_MANIFEST="${PLAYTHROUGH_DIR}/manifest.jsonl"
export PLAYTHROUGH_TIMELINE="${PLAYTHROUGH_DIR}/timeline.json"

# The capture telemetry sidecar, and why it exists SEPARATELY from the
# manifest rather than as extra manifest columns.
#
# The manifest schema is exactly six fields -- frame, file, real_ts,
# ingame_clock, action, commentary -- and that is a contract, not a
# convenience.  But the clock parser is required to be defensive, and
# a defensive parser needs the sidebar DATE line
# (display::date_string, src/display.cpp:194-205) as well as the
# clock: without it, a clock that reads 08:00:00 and then 07:59:00 is
# indistinguishable from a genuine crossing of midnight, and an action
# spanning a full day is undercounted by exactly 24 hours because the
# time of day came back the same.
#
# So the date is recorded HERE, keyed by frame, and timeline.py
# cross-checks its rollover and day-count decisions against it.  One
# JSON object per line, append-only.  capture.sh REPORTS the row on its
# machine payload and names this path in it; the row is appended by
# session.py, which already owns the frame counter and the manifest row
# for the same frame, so one logical record has one writer.  A frame
# that was captured twice therefore has two rows and the LAST one wins,
# which is the same last-occurrence rule the engine itself applies to
# duplicated option entries.
#
# It lives under playthrough/build/ because it is an intermediate,
# recomputable observation record rather than a delivered artifact,
# and because putting it beside manifest.jsonl would invite exactly
# the confusion the six-field contract exists to prevent.
export PLAYTHROUGH_OBSERVATIONS="${PLAYTHROUGH_BUILD_DIR}/\
observations.jsonl"
export PLAYTHROUGH_CONCAT_LIST="${PLAYTHROUGH_BUILD_DIR}/concat.txt"

# The per-frame DATE AUDIT.  One JSON object per captured frame,
# recording the sidebar date line -- display::date_string()
# (src/display.cpp:193-205) -- beside the clock that was read from the
# same frame.
#
# It exists because the six-field manifest schema is fixed and carries
# no date column, while timeline.py's midnight-rollover decision needs
# one: without date evidence a reading that goes backwards cannot be
# told apart from a crossing of midnight, and inventing the difference
# would be a fabrication.  So the date is persisted HERE, beside the
# manifest rather than inside it, which keeps the manifest's schema
# untouched and still gives the timeline real evidence to decide on.
# ocr_clock.py appends to it (it is the module that reads the line) and
# timeline.py consumes it.  It lives in build/ because it is derived
# evidence rather than a narrative artifact.
export PLAYTHROUGH_DATE_AUDIT="${PLAYTHROUGH_BUILD_DIR}/frame_dates.jsonl"
export PLAYTHROUGH_MOVIE="${PLAYTHROUGH_DIR}/cata-play.mp4"
export PLAYTHROUGH_MOVIE_CC="${PLAYTHROUGH_DIR}/cata-play-cc.mp4"
export PLAYTHROUGH_TRANSCRIPT_MD="${PLAYTHROUGH_DIR}/transcript.md"
export PLAYTHROUGH_TRANSCRIPT_SRT="${PLAYTHROUGH_DIR}/transcript.srt"
export PLAYTHROUGH_DOSSIER="${PLAYTHROUGH_DIR}/dossier.md"
export PLAYTHROUGH_TECH_NOTES="${PLAYTHROUGH_DIR}/TECHNICAL_NOTES.md"
export PLAYTHROUGH_REQUIREMENTS="${PLAYTHROUGH_TOOLING_DIR}/requirements.txt"

# One printf format for the capture filename, so the capturer, the
# manifest writer and the concat list agree byte for byte.  Use it as
#     name="$(printf -- "${PLAYTHROUGH_FRAME_FORMAT}" "${index}")"
# The 5-digit zero-padded field keeps a lexical sort identical to a
# numeric one, which is what makes the concat list trivially correct.
export PLAYTHROUGH_FRAME_FORMAT='frame_%05d.png'
export PLAYTHROUGH_TRANSITION_FORMAT='trans_%05d_%02d.png'

# The game, and the exact command-line forms it is launched with.
# Both stay repository-root relative on purpose (see WORKING
# DIRECTORY): the trailing slash on the userdir matches
# as_norm_dir()'s own normalisation at src/path_info.cpp:105.
export PLAYTHROUGH_GAME_BIN="${_playthrough_repo_root}/cataclysm-tiles"
export PLAYTHROUGH_GAME_BIN_ARG="./cataclysm-tiles"
export PLAYTHROUGH_USERDIR_ARG="./playthrough/userdir/"

# Diagnostic logs, inside the private runtime root established above --
# which is already suffixed per checkout, so parallel clones cannot
# overwrite each other's diagnostics and no name here needs a suffix of
# its own.  They stay outside the working tree deliberately: they are
# diagnostics, not artifacts, and `!/playthrough/**` would otherwise
# make them committable.
export PLAYTHROUGH_GAME_LOG="${PLAYTHROUGH_LOG_DIR}/cata-play.log"
export PLAYTHROUGH_XVFB_LOG="${PLAYTHROUGH_LOG_DIR}/xvfb.log"
export PLAYTHROUGH_WM_LOG="${PLAYTHROUGH_LOG_DIR}/openbox.log"

# Pid files for the two host processes this file can start.  They are
# recorded so that a later stage can ask whether the server it is
# about to use is one WE started -- which is the difference between
# reporting "the X server we launched has died" and reporting nothing
# at all -- and so that a diagnostic teardown never has to guess a pid
# or match a process by name pattern.  They live in the runtime root's
# run/ directory for the same reason the logs live in log/: a
# predictable name in world-writable /tmp is how another account plants
# a symlink and redirects the truncating write that records a pid.
export PLAYTHROUGH_XVFB_PIDFILE="${PLAYTHROUGH_RUN_DIR}/xvfb.pid"
export PLAYTHROUGH_WM_PIDFILE="${PLAYTHROUGH_RUN_DIR}/openbox.pid"

# The supervisor program names that own the headless surface durably
# when a supervisor is configured on this host.  Detachment alone does
# not survive a teardown of the whole process tree (see PROCESS
# LIFECYCLE below), so a supervisor is preferred whenever one answers.
# The per-clone suffix keeps two checkouts from asking one supervisor
# program to serve two displays.
export PLAYTHROUGH_SUPERVISOR_XVFB="playthrough-xvfb\
${_playthrough_suffix}"
export PLAYTHROUGH_SUPERVISOR_WM="playthrough-openbox\
${_playthrough_suffix}"

# The X authority file: a per-run 128-bit MIT-MAGIC-COOKIE-1 for the
# contracted display, kept 0600 inside the private runtime root.
#
# An XAUTHORITY the caller already exported is left alone, so that an
# externally provisioned authenticated display -- a container sidecar
# with its own cookie, say -- keeps working; ours is used whenever the
# caller has none, which is the case this pipeline actually runs in.
export PLAYTHROUGH_XAUTHORITY="${PLAYTHROUGH_RUNTIME_DIR}/Xauthority"
if [ -n "${XAUTHORITY:-}" ] &&
   [ "${XAUTHORITY}" != "${PLAYTHROUGH_XAUTHORITY}" ] &&
   [ -f "${XAUTHORITY}" ]; then
    export PLAYTHROUGH_XAUTHORITY_ORIGIN="inherited"
else
    export PLAYTHROUGH_XAUTHORITY_ORIGIN="pipeline"
    export XAUTHORITY="${PLAYTHROUGH_XAUTHORITY}"
fi

# ---------------------------------------------------------------------
# Display, window and grid geometry
#
# THREE RECTANGLES, THREE NAMES.  They are different sizes, so the
# pipeline never calls two of them by one name:
#
#   X ROOT             1920x1080 at depth 24.  The capture target, and
#                      the only geometry this file asserts.
#   GAME X WINDOW      the window openbox gives the borderless game.
#                      Its size is the window manager's decision, not
#                      the engine's: FULLSCREEN defaults to "windowedbl"
#                      (src/options.cpp:2715-2724) and a borderless
#                      window may be sized to the whole screen.
#                      Measured on this surface: 1920x1080+0+0, border
#                      width 0.  launch_game.sh reports what it finds
#                      rather than assuming either outcome.
#   TERMINAL RENDER    1920x1072 -- the 240x67 cell canvas the engine
#   GRID               paints, 240 columns x 8 px by 67 rows x 16 px
#                      (src/sdltiles.cpp:595-596; under windowed
#                      borderless the engine recomputes the grid from
#                      the window it actually got, :669-675, so 1080/16
#                      floors to 67 rows).  It is blitted at the
#                      window's TOP-LEFT and the leftover pixels are
#                      border (src/sdltiles.cpp:311-320, :1046-1050);
#                      the contracted placement of that 1072-px grid in
#                      the 1080-px root leaves a four-pixel band, which
#                      is where the sidebar crop's +4 comes from.
#
# Capture therefore targets the ROOT: it yields a true-resolution PNG
# whose only non-game pixels are that thin band, and it needs no
# rescaling -- rescaling would soften exactly the 8x16 glyphs the clock
# OCR depends on.  Photographing the game X window instead would hand
# downstream a frame whose size depends on the window manager.
#
# The window is found by CLASS.  `xdotool search --name 'Cataclysm'`
# returns nothing for this window even though xwininfo -root
# -children lists it; `xdotool search --class cataclysm-tiles` works.
#
# Note also that xdotool has NO --display option -- it rejects the flag
# and resolves the display from the environment instead.  Exporting
# DISPLAY above is therefore what makes every xdotool call in the
# pipeline work; a per-command flag is not an available alternative.
# ---------------------------------------------------------------------
export PLAYTHROUGH_SCREEN_WIDTH=1920
export PLAYTHROUGH_SCREEN_HEIGHT=1080
export PLAYTHROUGH_SCREEN_DEPTH=24
export PLAYTHROUGH_SCREEN="1920x1080x24"
export PLAYTHROUGH_WINDOW_CLASS="cataclysm-tiles"

# Terminal grid and font cell, used to seed options.json and to
# compute the sidebar OCR crop rather than hard-coding a rectangle.
# 36 cells is the default sidebar width from
# data/json/ui/sidebar.json:7 (custom_sidebar.width).  Measured in
# this checkout, not estimated: nine sidebar*.json files ship at the
# top level of data/json/ui/ -- eight alternatives to that default --
# and across the whole tree twelve widgets declare "style": "sidebar"
# at eight distinct widths (32, 36, 43, 44, 48, 58, 62, 66).  That is
# why the crop is computed by sidebar_geometry.py and never a literal.
export PLAYTHROUGH_TERMINAL_X=240
export PLAYTHROUGH_TERMINAL_Y=67
export PLAYTHROUGH_FONT_WIDTH=8
export PLAYTHROUGH_FONT_HEIGHT=16

# The sidebar width in cells that the engine's own DEFAULT layout
# carries, recorded here for reporting only.
#
# It is 44, not 36, and the difference matters: panel_manager()
# initialises current_layout_id to "legacy_labels_sidebar" on every
# non-Android build (src/panels.cpp:412-418), whose widget declares
# "width": 44 (data/json/ui/sidebar-legacy-labels.json), while
# custom_sidebar's 36 is merely one of the eight shipped presets.  A
# fresh userdir therefore renders a 352 px sidebar, not a 288 px one.
#
# sidebar_geometry.py deliberately does NOT read this value.  It
# resolves the ACTIVE layout from <userdir>/config/panel_options.json,
# falling back to the engine's own default, and then reads that
# layout's width out of the game's widget JSON -- because a constant
# here, honoured there, is exactly the hard-coded rectangle the
# computed crop exists to eliminate.  This export is for logs and
# status output; the crop comes from the game's own configuration.
export PLAYTHROUGH_SIDEBAR_CELLS=44
export PLAYTHROUGH_SIDEBAR_LAYOUT="legacy_labels_sidebar"

# THE TILESET IS REQUIRED, NOT PREFERRED.
#
# The value is the NAME: field of the installed tileset.txt rather than
# its display VIEW: name -- src/options.cpp:1213-1227 reads NAME: as
# the option value and VIEW: only as the menu label -- so the directory
# gfx/MShockXotto+ declares the id MshockXottoplus with the view
# "MSXotto+".
#
# THERE IS DELIBERATELY NO FALLBACK.  The requirement is to install the
# CDDA-Tilesets pack and configure MSXotto+, so a run that quietly came
# up on the checkout's own ASCIITiles would satisfy the letter of "the
# game rendered tiles" while failing the requirement outright -- and it
# would do so invisibly, because an ASCII capture looks like a
# perfectly good frame.  launch_game.sh therefore HYDRATES this tileset
# from the pre-placed pack when it is absent and FAILS NON-ZERO when it
# cannot, and seed_options.py refuses to write any other id.  An
# operator who genuinely wants a different tileset says so by exporting
# PLAYTHROUGH_TILESET, which is validated against what is installed
# just as strictly; nothing is substituted behind their back.
export PLAYTHROUGH_TILESET="MshockXottoplus"

# Every name the required pack is known by, so a lookup can match the
# id, the view label, or the directory the pack ships as.  This is a
# spelling aid for ONE tileset, not a list of acceptable alternatives.
export PLAYTHROUGH_TILESET_ALIASES="MshockXottoplus MSXotto+ MShockXotto+"

# DIAGNOSTIC ONLY, and unreachable unless it is asked for by name.
# The checkout's own tileset -- the one thing that is always installed,
# because .gitignore:52 negates it -- so that somebody debugging the
# pipeline on a host with no pack can still bring the game up and look
# at a frame.  It is NOT a fallback: nothing consults it unless
# PLAYTHROUGH_ALLOW_TILESET_FALLBACK=1 is set deliberately, and
# launch_game.sh says so loudly on stderr and records origin=fallback
# when it does.  A session recorded under it does not satisfy the
# requirement, which names MSXotto+.
export PLAYTHROUGH_TILESET_FALLBACK="ASCIITiles"

# Seconds to let a frame settle after a keystroke before capturing.
# The game redraws asynchronously; capturing too early photographs the
# previous frame and silently shifts every clock reading by one step.
export PLAYTHROUGH_SETTLE_SECONDS="0.3"

# ---------------------------------------------------------------------
# The Python interpreter
#
# Resolved here so that every sibling runs the same one, and searched
# out of tree only -- a virtualenv inside playthrough/ would be
# re-included by `!/playthrough/**` and committed.  Honour an explicit
# PLAYTHROUGH_PYTHON first, then PLAYTHROUGH_VENV, then the
# provisioned location, then whatever python3 is on PATH.  Install
# playthrough/tooling/requirements.lock into whichever one is chosen.
#
# AND THEN VERIFY IT.  This value can come straight from the
# environment, and the interpreter it names is handed the manifest
# writer, the option seeder and the OCR module -- so "it exists and is
# executable" is not a sufficient test.  playthrough_verify_executable
# insists that neither the interpreter nor any directory above it is
# group- or world-writable or owned by a third party, which is what
# stops an unattended run from executing a planted interpreter.  A
# failure here is fatal by design; PLAYTHROUGH_ALLOW_UNVERIFIED_EXECUTABLES=1
# downgrades it to a warning for interactive diagnosis only.
# ---------------------------------------------------------------------
if [ -n "${PLAYTHROUGH_PYTHON:-}" ] &&
   [ -x "${PLAYTHROUGH_PYTHON}" ]; then
    _playthrough_python="${PLAYTHROUGH_PYTHON}"
elif [ -n "${PLAYTHROUGH_VENV:-}" ] &&
     [ -x "${PLAYTHROUGH_VENV}/bin/python" ]; then
    _playthrough_python="${PLAYTHROUGH_VENV}/bin/python"
elif [ -x "/opt/playthrough-venv/bin/python" ]; then
    _playthrough_python="/opt/playthrough-venv/bin/python"
else
    _playthrough_python="$(command -v python3 2>/dev/null || true)"
    if [ -z "${_playthrough_python}" ]; then
        playthrough_warn "no python3 found on PATH; the render" \
            "stages will not run until one is available"
        _playthrough_python="python3"
    fi
fi
export PLAYTHROUGH_PYTHON="${_playthrough_python}"

# Skip verification only when nothing was found at all: there is then no
# file to check, and the warning above has already been printed.  The
# render stages fail later with a clear message rather than silently.
case "${_playthrough_python}" in
    */*)
        if ! playthrough_verify_executable \
                "${_playthrough_python}" "PLAYTHROUGH_PYTHON"; then
            if [ "${PLAYTHROUGH_ALLOW_UNVERIFIED_EXECUTABLES:-0}" \
                    = "1" ]; then
                playthrough_warn "using the unverified interpreter" \
                    "'${_playthrough_python}' because" \
                    "PLAYTHROUGH_ALLOW_UNVERIFIED_EXECUTABLES=1." \
                    "The trust state is therefore diagnostic: a" \
                    "capture launch and a production capture will both" \
                    "refuse to run while it is set (see THE TRUST" \
                    "STATE below)."
            else
                playthrough_die "refusing to run the pipeline's" \
                    "Python through '${_playthrough_python}'." \
                    "Point PLAYTHROUGH_PYTHON or PLAYTHROUGH_VENV at" \
                    "an interpreter that only root or this user can" \
                    "write, with no group- or world-writable" \
                    "directory above it -- /opt/playthrough-venv is" \
                    "the provisioned one.  Or set" \
                    "PLAYTHROUGH_ALLOW_UNVERIFIED_EXECUTABLES=1 to" \
                    "accept this host's layout deliberately, which a" \
                    "recorded session must not do."
                return 1 2>/dev/null || exit 1
            fi
        fi
        ;;
esac

# ---------------------------------------------------------------------
# AND THEN CHECK WHICH PYTHON IT IS.
#
# playthrough/tooling/requirements.lock pins CPython 3.12 wheels for
# manylinux x86_64, because numpy and Pillow ship per-interpreter
# binaries and there is no such thing as a version-agnostic wheel for
# either.  So "an interpreter was found and it is trustworthy" is still
# not enough: the resolved interpreter has to be the one the lock was
# built for, or the environment an operator provisioned is not the
# environment the pipeline is about to run.  The failure without this
# check is quiet in exactly the way this pipeline cannot afford --
# `python3 -m venv .venv` under a host whose python3 is 3.13 installs
# into ONE interpreter while the pipeline runs another, or refuses the
# lock's hashes with a message about the wheel rather than about the
# interpreter.
#
# The version is REPORTED as well as checked, so the committed record
# of a session says which interpreter produced it: env_summary prints
# PLAYTHROUGH_PYTHON_VERSION beside the path.
#
# A mismatch WARNS rather than refuses, and the distinction is
# deliberate: a lock regenerated for another interpreter is perfectly
# legitimate (the lock says so itself, and says to regenerate rather
# than relax), so this cannot be a hard failure without breaking a
# supported workflow.  What it must not be is silent.
# ---------------------------------------------------------------------
export PLAYTHROUGH_PYTHON_ABI="3.12"
_playthrough_python_version=""
if [ -x "${_playthrough_python}" ]; then
    _playthrough_python_version="$(
        "${_playthrough_python}" -c \
            'import sys
print("%d.%d.%d" % sys.version_info[:3])' 2>/dev/null || true)"
fi
export PLAYTHROUGH_PYTHON_VERSION="${_playthrough_python_version}"
case "${_playthrough_python_version}" in
    "${PLAYTHROUGH_PYTHON_ABI}".*)
        ;;
    '')
        playthrough_warn "could not ask" \
            "'${_playthrough_python}' for its version, so it cannot be" \
            "confirmed to be the CPython ${PLAYTHROUGH_PYTHON_ABI} that" \
            "playthrough/tooling/requirements.lock pins wheels for." \
            "Check that PLAYTHROUGH_PYTHON names a working interpreter."
        ;;
    *)
        playthrough_warn "the resolved interpreter" \
            "'${_playthrough_python}' is Python" \
            "${_playthrough_python_version}, but" \
            "playthrough/tooling/requirements.lock pins CPython" \
            "${PLAYTHROUGH_PYTHON_ABI} wheels -- numpy and Pillow are" \
            "per-interpreter binaries, so that lock cannot be installed" \
            "into this one.  Point PLAYTHROUGH_VENV or" \
            "PLAYTHROUGH_PYTHON at a CPython" \
            "${PLAYTHROUGH_PYTHON_ABI} environment" \
            "(/opt/playthrough-venv is the provisioned one), or" \
            "regenerate the lock for this interpreter as its own header" \
            "describes."
        ;;
esac

# ---------------------------------------------------------------------
# Helper functions
#
# None of these runs at source time.  Sourcing this file must never
# start a server, launch the game or write into the working tree; the
# launcher calls what it needs, explicitly.
# ---------------------------------------------------------------------

# playthrough_assert_video_driver
#   The guard that keeps the black-movie failure mode impossible.
#   Call it from any stage that is about to render or capture.
playthrough_assert_video_driver() {
    if [ "${SDL_VIDEODRIVER:-}" != "x11" ]; then
        playthrough_die "SDL_VIDEODRIVER is" \
            "'${SDL_VIDEODRIVER:-<unset>}', not 'x11'." \
            "The dummy backend renders zero pixels and produces a" \
            "movie that is entirely black while every count still" \
            "matches.  Re-source playthrough/tooling/env.sh and do" \
            "not override it."
        return 1
    fi
    return 0
}

# ---------------------------------------------------------------------
# THE TRUST STATE -- ONE CONTRACT, DEFINED HERE, ENFORCED DOWNSTREAM
#
# Several checks in this pipeline can be relaxed for diagnosis: an
# interpreter or tool that cannot be verified, a display this pipeline
# did not start and cannot prove is authenticated, a tileset pack on a
# world-writable path, artwork other than the required MSXotto+, a
# Pillow older than the pin, a compiler the project does not sanction.
# Each of those exists for a real reason -- without them this pipeline
# cannot be debugged on a host it does not own -- and each was, until
# now, enforced only by a WARNING that said not to record a session
# under it.
#
# THAT IS NOT A CONTROL.  A warning on stderr does not stop the very
# next command from capturing a frame, committing it, and presenting it
# as evidence of an unobserved session played in the required artwork
# through a verified toolchain.  Operator discipline is not a security
# boundary, and this pipeline's whole output is an integrity claim.
#
# So the state is authoritative and there is exactly one of it:
#
#   PLAYTHROUGH_TRUST_BYPASS_VARS  every variable that relaxes a check
#   PLAYTHROUGH_TRUST_BYPASSES     those of them currently active
#   PLAYTHROUGH_TRUST_STATE        trusted | diagnostic
#
# and two consumers act on it without discretion: launch_game.sh
# refuses to start or accept an instance that will be captured, and
# capture.sh refuses a production capture -- both BEFORE anything is
# created, so a diagnostic run produces nothing that could be mistaken
# for evidence.  Diagnosis stays fully available: capture.sh's
# diagnostic mode withdraws its frame out of the working tree and never
# exits 0, so a relaxed run is structurally uncommittable rather than
# forbidden.
#
# RECOMPUTED AT EVERY CALL, never memoised.  A caller can export one of
# these variables after sourcing this file -- a test harness does
# exactly that -- so an answer cached at source time would be a
# statement about the past.  The cost is a loop over six names.
#
# ANY VALUE OTHER THAN EMPTY OR "0" COUNTS AS ACTIVE, which is stricter
# than the individual check sites (they act only on "1").  That is
# deliberate: `PLAYTHROUGH_ALLOW_UNAUTHENTICATED_X=true` does not
# actually relax the X check, but it is unambiguous evidence that
# somebody meant to relax it, and a recorded session is not the place to
# be generous about a security-relevant variable whose spelling is
# wrong.  Fail closed.
# ---------------------------------------------------------------------
export PLAYTHROUGH_TRUST_BYPASS_VARS="\
PLAYTHROUGH_ALLOW_UNVERIFIED_EXECUTABLES \
PLAYTHROUGH_ALLOW_UNAUTHENTICATED_X \
PLAYTHROUGH_ALLOW_UNVERIFIED_TILESET_PACK \
PLAYTHROUGH_ALLOW_TILESET_FALLBACK \
PLAYTHROUGH_ALLOW_VULNERABLE_PILLOW \
PLAYTHROUGH_ALLOW_ANY_COMPILER"

# playthrough_trust_reason NAME
#   What NAME endangers, in one sentence, so a refusal explains itself
#   instead of naming a variable and stopping.
playthrough_trust_reason() {
    case "${1-}" in
        PLAYTHROUGH_ALLOW_UNVERIFIED_EXECUTABLES)
            printf '%s' "a tool or interpreter that another account \
can replace decides every reading in the film"
            ;;
        PLAYTHROUGH_ALLOW_UNAUTHENTICATED_X)
            printf '%s' "any local account can read the screen being \
captured and inject keystrokes into the session"
            ;;
        PLAYTHROUGH_ALLOW_UNVERIFIED_TILESET_PACK)
            printf '%s' "the artwork ingested into gfx/ came from a \
path this host cannot vouch for"
            ;;
        PLAYTHROUGH_ALLOW_TILESET_FALLBACK)
            printf '%s' "the run may render artwork other than the \
required MSXotto+, which no other check would notice"
            ;;
        PLAYTHROUGH_ALLOW_VULNERABLE_PILLOW)
            printf '%s' "frames are decoded by a Pillow older than \
the pinned, reviewed one"
            ;;
        PLAYTHROUGH_ALLOW_ANY_COMPILER)
            printf '%s' "the binary may have been built by a compiler \
the project does not sanction"
            ;;
        *)
            printf '%s' "an unrecognised trust override is set"
            ;;
    esac
}

# playthrough_trust_refresh
#   Recompute the trust state from the environment as it is NOW, export
#   it, and report it: 0 when trusted, 1 when any bypass is active.
#   Silent -- the messages belong to the caller that refuses.
playthrough_trust_refresh() {
    local name value active=""
    local -a names=()
    read -r -a names <<<"${PLAYTHROUGH_TRUST_BYPASS_VARS}"
    for name in "${names[@]}"; do
        value="${!name-}"
        case "${value}" in
            ''|0)
                ;;
            *)
                active="${active}${active:+ }${name}"
                ;;
        esac
    done
    export PLAYTHROUGH_TRUST_BYPASSES="${active}"
    if [ -n "${active}" ]; then
        export PLAYTHROUGH_TRUST_STATE="diagnostic"
        return 1
    fi
    export PLAYTHROUGH_TRUST_STATE="trusted"
    return 0
}

# playthrough_trust_explain
#   One warning per active bypass, naming the variable, its value and
#   what it endangers.  Prints nothing when the state is trusted.
playthrough_trust_explain() {
    playthrough_trust_refresh && return 0
    local name
    local -a names=()
    read -r -a names <<<"${PLAYTHROUGH_TRUST_BYPASSES}"
    for name in "${names[@]}"; do
        playthrough_warn "${name}=${!name-} is set: $(
            playthrough_trust_reason "${name}")"
    done
    return 1
}

# playthrough_assert_trusted [CONTEXT]
#   THE GATE.  Call it from anything that is about to produce evidence.
#   Returns 0 when no bypass is active; otherwise explains every active
#   one and refuses, returning 1 (this file is sourced, so it cannot
#   exit -- the caller turns the refusal into its own exit code).
playthrough_assert_trusted() {
    local context="${1:-an action that produces evidence}"
    if playthrough_trust_refresh; then
        return 0
    fi
    playthrough_trust_explain
    playthrough_die "refusing ${context} while the trust state is" \
        "diagnostic (${PLAYTHROUGH_TRUST_BYPASSES// /, }).  Evidence" \
        "produced under a relaxed check is not evidence: unset the" \
        "variable(s) above and fix what each one was hiding, or keep" \
        "diagnosing with PLAYTHROUGH_CAPTURE_MODE=diagnostic, whose" \
        "frames are withdrawn out of the working tree and can never be" \
        "committed as part of the record."
    return 1
}

# ---------------------------------------------------------------------
# WHICH APT PACKAGE SHIPS WHICH COMMAND
#
# Named here so that a missing-tool diagnostic can say what to
# install rather than only what is absent.  A reader who is told
# "xdpyinfo is missing" still has to go and find out that it lives in
# x11-utils; being told the package is the difference between a
# two-minute fix and a search.  The list is the apt block in
# playthrough/tooling/requirements.txt, which is the single inventory
# of the system packages this pipeline needs.
# ---------------------------------------------------------------------
playthrough_tool_package() {
    case "$1" in
        Xvfb) printf '%s\n' "xvfb" ;;
        openbox) printf '%s\n' "openbox" ;;
        xdpyinfo|xwininfo|xprop) printf '%s\n' "x11-utils" ;;
        xdotool) printf '%s\n' "xdotool" ;;
        import|convert|identify) printf '%s\n' "imagemagick" ;;
        ffmpeg|ffprobe) printf '%s\n' "ffmpeg" ;;
        tesseract) printf '%s\n' "tesseract-ocr" ;;
        scrot) printf '%s\n' "scrot" ;;
        make) printf '%s\n' "make" ;;
        ccache) printf '%s\n' "ccache" ;;
        setsid|nohup|kill|env|readlink|tr|head|tail|sleep|mkdir|chmod|\
sha256sum|stat|timeout|id|realpath|cut|cp|mv|rm|wc|dirname|basename|\
cat|ls|sort|touch|pwd|date)
            printf '%s\n' "coreutils" ;;
        flock) printf '%s\n' "util-linux" ;;
        xauth) printf '%s\n' "xauth" ;;
        grep) printf '%s\n' "grep" ;;
        awk) printf '%s\n' "mawk or gawk" ;;
        sed) printf '%s\n' "sed" ;;
        supervisorctl) printf '%s\n' "supervisor" ;;
        *) printf '%s\n' "unknown package" ;;
    esac
}

# playthrough_tool_var NAME
#   The variable a resolved tool is exported as: `convert` becomes
#   PLAYTHROUGH_BIN_CONVERT and `g++-14` becomes PLAYTHROUGH_BIN_G__14.
#
#   Everything that is not a letter or a digit becomes an underscore,
#   because real command names contain characters a shell variable name
#   cannot -- `g++` is the one that matters here, and mapping only '.'
#   and '-' would produce the unassignable name PLAYTHROUGH_BIN_G++.
playthrough_tool_var() {
    printf 'PLAYTHROUGH_BIN_%s\n' \
        "$(printf '%s' "${1-}" |
            tr '[:lower:]' '[:upper:]' |
            tr -c '[:upper:][:digit:]' '_')"
}

# playthrough_resolve_tool NAME
#   Resolve NAME on PATH, verify it, and export PLAYTHROUGH_BIN_<NAME>
#   with the path that will actually be invoked.
#
#   The EXPORTED value is the resolved PATH entry, not its realpath, and
#   that distinction is deliberate: ImageMagick dispatches on argv[0]
#   (/usr/bin/convert is a symlink to magick on this host), so invoking
#   the link target would change the tool's behaviour.  The realpath is
#   what gets VERIFIED -- ownership and writability of the real binary
#   and of every directory above it -- which is the half that matters
#   for trust.
#
#   Returns 1 when the tool is absent or fails verification, so callers
#   can distinguish "install it" from "it exists"; the message on stderr
#   says which.
playthrough_resolve_tool() {
    local name="${1-}"
    # The permitted set is the one real tool names actually use --
    # letters, digits, '.', '_', '-' and '+' (g++, clang++-18) -- and
    # nothing else, so no path separator, no whitespace and no shell
    # metacharacter can arrive here in the guise of a command name.
    case "${name}" in
        ''|*[!A-Za-z0-9._+-]*)
            playthrough_die "'${name}' is not a plain command name"
            return 1
            ;;
    esac
    local path var
    path="$(command -v "${name}" 2>/dev/null || true)"
    if [ -z "${path}" ] || [ "${path#/}" = "${path}" ]; then
        return 1
    fi
    if ! playthrough_verify_executable "${path}" "${name}"; then
        if [ "${PLAYTHROUGH_ALLOW_UNVERIFIED_EXECUTABLES:-0}" \
                != "1" ]; then
            return 1
        fi
        playthrough_warn "using the unverified '${name}' at" \
            "'${path}' because" \
            "PLAYTHROUGH_ALLOW_UNVERIFIED_EXECUTABLES=1, which holds" \
            "the trust state at diagnostic and makes a capture launch" \
            "and a production capture refuse"
    fi
    var="$(playthrough_tool_var "${name}")"
    export "${var}=${path}"
    return 0
}

# playthrough_require_tools [tool ...]
#   Assert that external commands exist AND are trustworthy, reporting
#   ALL that fail rather than dying on the first, naming the package that
#   ships each missing one, and exporting a verified
#   PLAYTHROUGH_BIN_<NAME> for each that passes so callers invoke a
#   checked path instead of re-searching PATH themselves.  With no
#   arguments it checks the whole pipeline's toolchain.
#
#   THIS IS CALLED AT THE POINT OF USE, not only once up front.  Every
#   helper below that shells out asserts its own tools first, because
#   the alternative was measured to be actively misleading: with
#   x11-utils absent, `xdpyinfo` simply is not found, the probe fails,
#   and the operator is told there is no X server on :99 -- sending
#   them to debug a display that is in fact running perfectly.  A
#   missing tool and an absent server are different faults and are
#   reported differently.
playthrough_require_tools() {
    local tools=("$@")
    local missing=()
    local rejected=()
    local tool
    if [ "${#tools[@]}" -eq 0 ]; then
        tools=(
            Xvfb openbox xdpyinfo xwininfo xprop xdotool xauth
            import convert identify ffmpeg ffprobe tesseract flock
            setsid nohup grep awk sed
        )
    fi
    for tool in "${tools[@]}"; do
        if ! command -v "${tool}" >/dev/null 2>&1; then
            missing+=("${tool} ($(playthrough_tool_package \
                "${tool}"))")
        elif ! playthrough_resolve_tool "${tool}"; then
            rejected+=("${tool}")
        fi
    done
    if [ "${#missing[@]}" -ne 0 ] || [ "${#rejected[@]}" -ne 0 ]; then
        # ABSENT AND UNTRUSTWORTHY ARE DIFFERENT FAULTS and are reported
        # as such: one is answered by installing a package, the other by
        # finding out who owns a binary this pipeline is being asked to
        # run.  Reporting them together as "missing" sent an operator to
        # apt for a tool that was already installed.
        if [ "${#missing[@]}" -ne 0 ]; then
            playthrough_die "missing required command(s), with the" \
                "package that ships each:" "${missing[*]}." \
                "See the apt list in" \
                "playthrough/tooling/requirements.txt."
        fi
        if [ "${#rejected[@]}" -ne 0 ]; then
            playthrough_die "command(s) found but rejected as" \
                "untrustworthy:" "${rejected[*]}.  The reason for" \
                "each is reported above; an unattended pipeline does" \
                "not run a binary it cannot vouch for.  Install the" \
                "packaged tool, or set" \
                "PLAYTHROUGH_ALLOW_UNVERIFIED_EXECUTABLES=1 to accept" \
                "this host's layout deliberately -- which a recorded" \
                "session must not do."
        fi
        return 1
    fi
    return 0
}

# playthrough_display_probe
#   Three-way answer about the contracted display, because two
#   different faults would otherwise wear the same face:
#     0  a server is answering
#     1  no server is answering
#     2  xdpyinfo is not installed, so the question was never asked
#   Callers that only want a boolean use playthrough_display_ready;
#   callers that report to a human use this, so "x11-utils is not
#   installed" cannot be printed as "no X server".
playthrough_display_probe() {
    if ! command -v xdpyinfo >/dev/null 2>&1; then
        return 2
    fi
    if xdpyinfo -display "${PLAYTHROUGH_DISPLAY}" >/dev/null 2>&1; then
        return 0
    fi
    return 1
}

# playthrough_display_ready
#   True when an X server is answering on the contracted display.
#   A missing xdpyinfo is NOT ready, and the distinction is reported
#   once so it cannot be mistaken for a dead server on every poll.
playthrough_display_ready() {
    playthrough_display_probe
    case "$?" in
        0) return 0 ;;
        2)
            playthrough_warn "xdpyinfo is not installed (package" \
                "x11-utils), so whether a server is answering on" \
                "${PLAYTHROUGH_DISPLAY} cannot be determined; this" \
                "is a MISSING TOOL, not a missing display"
            return 1
            ;;
    esac
    return 1
}

# playthrough_wait_for_display [timeout_seconds]
#   Poll until the display answers.  Default timeout 30 s.
#
#   The timeout is validated before it reaches arithmetic.  This is not
#   defensive tidiness: bash evaluates command substitution inside an
#   arithmetic expansion, so `$(( timeout * 4 ))` on an unchecked
#   caller-supplied string is an execution primitive.
playthrough_wait_for_display() {
    playthrough_require_tools xdpyinfo || return 1
    playthrough_validate_int "${1:-30}" "display wait timeout" 1 3600 ||
        return 1
    local timeout="${PLAYTHROUGH_INT}"
    local deadline=$(( timeout * 4 ))
    local waited=0
    while [ "${waited}" -lt "${deadline}" ]; do
        if playthrough_display_ready; then
            return 0
        fi
        sleep 0.25
        waited=$(( waited + 1 ))
    done
    playthrough_die "no X server answering on" \
        "${PLAYTHROUGH_DISPLAY} after ${timeout}s (log:" \
        "${PLAYTHROUGH_XVFB_LOG})"
    return 1
}

# ---------------------------------------------------------------------
# PROCESS LIFECYCLE -- WHAT DETACHMENT DOES AND DOES NOT BUY
#
# Read this before relying on anything below to still be running.
#
# `setsid nohup CMD </dev/null >LOG 2>&1 & disown` is the strongest
# detachment a shell can perform, and it is the idiom this pipeline is
# specified to use: setsid puts the child in its own session and
# process group so a signal sent to the CALLER's group misses it,
# nohup detaches it from SIGHUP, </dev/null stops it from ever
# blocking on a vanished stdin, and disown removes it from this
# shell's job table so no exit-time cleanup reaches it.  It genuinely
# fixes the failure that was measured here: a `make` run terminated by
# Interrupt -- not OOM, not a compile error -- because an outer call
# timed out and signalled the whole process group.
#
# IT IS NOT, HOWEVER, DURABILITY, AND THIS FILE NO LONGER CLAIMS IT
# IS.  On a platform that tears down the entire process tree of a
# session -- an orchestrator killing a container's process namespace,
# a cgroup being emptied, a pod restarting -- a new session and group
# are no protection at all: nothing that was started from inside the
# torn-down tree survives it.  This has been observed here rather than
# theorised: a provisioned, supervised Xvfb-plus-openbox pair was found
# absent on a later call, with supervisord's own socket refusing
# connections, because the tree they lived in had been taken down
# between one automation call and the next.
#
# So the contract this file offers is deliberately narrower and
# honest, in this order of preference:
#
#   1. A DURABLE SUPERVISOR, when one is configured and reachable.
#      playthrough_supervisor_start hands the X server and the window
#      manager to it, which is the only arrangement in which they are
#      restarted rather than merely started.  On this host that is
#      supervisord with the playthrough-xvfb and playthrough-openbox
#      programs.
#   2. BEST-EFFORT DETACHMENT, verified.  playthrough_spawn_detached
#      uses the full idiom above AND then checks that the child is
#      actually alive, so a spawn that failed is a reported failure
#      instead of a silent absence.
#   3. RE-ASSERTION at the point of use.  playthrough_headless_up is
#      idempotent and cheap, so every stage calls it again rather than
#      trusting that an earlier stage's server is still there.  This
#      is the part that actually makes a multi-call pipeline work on a
#      platform with tree teardown, and it is why no caller may assume
#      liveness from a previous call.
#
# A stage that must not be interrupted at all -- the captured session
# itself -- belongs under ONE foreground guardian process rather than
# behind any of this: see launch_game.sh's `guard` subcommand, which
# runs the game in the foreground precisely so that its lifetime is
# the caller's lifetime and no detachment question arises.
# ---------------------------------------------------------------------

# playthrough_spawn_detached NAME PIDFILE LOGFILE -- CMD [ARG ...]
#   Start one long-lived child as detached as a shell can make it, and
#   PROVE it started.  Writes the child's pid to PIDFILE, returns 0
#   only when that pid is still alive a moment later, and reports the
#   log to look in when it is not.
#
#   The `--` separator is required so that a command whose own
#   arguments look like options cannot be mistaken for this
#   function's.  Nothing is passed through a shell: the command is an
#   argument list, which is also what keeps this file free of the
#   string interpolation the project's static analysis exists to
#   catch.
playthrough_spawn_detached() {
    local name="$1" pidfile="$2" logfile="$3"
    shift 3
    if [ "${1:-}" = "--" ]; then
        shift
    else
        playthrough_die "playthrough_spawn_detached: the command" \
            "must be introduced by --"
        return 1
    fi
    if [ "$#" -eq 0 ]; then
        playthrough_die "playthrough_spawn_detached: no command" \
            "given for '${name}'"
        return 1
    fi
    playthrough_require_tools setsid nohup "$1" || return 1
    local spawned=""
    # A lock descriptor is withheld from the child -- see
    # playthrough_child_close_fd.  Xvfb and openbox outlive this shell
    # by design, so an inherited lock would be held indefinitely.
    playthrough_child_close_fd || return 1
    setsid nohup "$@" >"${logfile}" 2>&1 </dev/null \
        {PLAYTHROUGH_CHILD_CLOSE_FD}>&- &
    spawned="$!"
    # disown removes the job from this shell's table so that no
    # exit-time cleanup in the caller can reach it.  It is the last
    # element of the specified idiom and the one most often left off.
    disown "${spawned}" 2>/dev/null || true
    playthrough_child_close_done
    if [ -n "${pidfile}" ]; then
        printf '%s\n' "${spawned}" >"${pidfile}" 2>/dev/null || \
            playthrough_warn "could not record ${name}'s pid" \
                "${spawned} in ${pidfile}"
    fi
    # A short settle, then proof of life.  Without this a command that
    # died instantly -- a missing shared library, a display already in
    # use -- would be reported as started, and the failure would
    # resurface later as an unexplained timeout somewhere else.
    sleep 0.25
    if ! kill -0 "${spawned}" 2>/dev/null; then
        playthrough_die "${name} exited immediately after being" \
            "started (pid ${spawned} is already gone); see" \
            "${logfile}"
        return 1
    fi
    playthrough_log "${name} started (pid ${spawned}, log:" \
        "${logfile}).  Detached, but NOT immune to a teardown of this" \
        "whole process tree -- callers re-assert rather than assume."
    return 0
}

# playthrough_supervisor_available
#   True when a process supervisor is installed AND answering.  Being
#   installed is not enough: supervisord's socket refuses connections
#   when the daemon itself is not running, which is exactly the state
#   a torn-down tree leaves behind.
playthrough_supervisor_available() {
    command -v supervisorctl >/dev/null 2>&1 || return 1
    supervisorctl status >/dev/null 2>&1
}

# playthrough_supervisor_start PROGRAM
#   Ask the supervisor to run one program and report whether it is
#   RUNNING afterwards.  Returns 1 when there is no supervisor, when
#   the program is not configured, or when it did not come up -- in
#   every one of those cases the caller falls back to verified
#   detachment, which is why this reports rather than dies.
playthrough_supervisor_start() {
    local program="$1"
    playthrough_supervisor_available || return 1
    local state
    state="$(supervisorctl status "${program}" 2>/dev/null || true)"
    case "${state}" in
        ""|*"no such process"*|*"ERROR"*) return 1 ;;
    esac
    case "${state}" in
        *RUNNING*) return 0 ;;
    esac
    playthrough_log "asking the supervisor to start ${program}," \
        "which owns its lifecycle durably"
    supervisorctl start "${program}" >/dev/null 2>&1 || true
    state="$(supervisorctl status "${program}" 2>/dev/null || true)"
    case "${state}" in
        *RUNNING*) return 0 ;;
    esac
    return 1
}

# playthrough_xauth_cookie
#   128 bits of hex for one MIT-MAGIC-COOKIE-1 entry.  mcookie is
#   preferred because it is purpose-built; /dev/urandom is the fallback
#   so a host without util-linux still gets a real random cookie rather
#   than something guessable.
playthrough_xauth_cookie() {
    if command -v mcookie >/dev/null 2>&1; then
        mcookie
        return 0
    fi
    od -An -tx1 -N16 /dev/urandom | tr -d ' \n'
    printf '\n'
}

# playthrough_ensure_xauth
#   Make sure the active XAUTHORITY file holds a cookie for this
#   display, generating one if it does not.
#
#   This is what makes an authenticated X server possible: the server is
#   started with -auth pointing at this same file, so only a client that
#   can read it may connect.  The file is created 0600 inside the
#   verified private runtime root -- a credential in a shared directory
#   is not a credential.  An XAUTHORITY inherited from the caller is
#   added to rather than replaced, so an externally provisioned display
#   keeps its own entries.
playthrough_ensure_xauth() {
    playthrough_require_tools xauth || return 1
    local file="${XAUTHORITY:-${PLAYTHROUGH_XAUTHORITY}}"
    if [ "${PLAYTHROUGH_XAUTHORITY_ORIGIN}" = "pipeline" ]; then
        playthrough_secure_file "${file}" 600 || return 1
    elif [ ! -f "${file}" ]; then
        playthrough_die "the inherited XAUTHORITY '${file}' does not" \
            "exist"
        return 1
    fi
    if xauth -f "${file}" list "${PLAYTHROUGH_DISPLAY}" 2>/dev/null |
            grep -q 'MIT-MAGIC-COOKIE-1'; then
        return 0
    fi
    local cookie
    cookie="$(playthrough_xauth_cookie 2>/dev/null || true)"
    cookie="${cookie%%[!0-9a-fA-F]*}"
    if [ "${#cookie}" -lt 32 ]; then
        playthrough_die "could not generate a 128-bit X cookie;" \
            "install util-linux for mcookie, or make /dev/urandom" \
            "readable"
        return 1
    fi
    if ! xauth -f "${file}" -q add "${PLAYTHROUGH_DISPLAY}" \
            MIT-MAGIC-COOKIE-1 "${cookie}"; then
        playthrough_die "xauth could not record a cookie for" \
            "${PLAYTHROUGH_DISPLAY} in ${file}"
        return 1
    fi
    playthrough_log "recorded a fresh MIT-MAGIC-COOKIE-1 for" \
        "${PLAYTHROUGH_DISPLAY} in ${file}"
    return 0
}

# ---------------------------------------------------------------------
# PROCESS LIFETIME -- WHAT setsid DOES AND WHAT IT DOES NOT DO.
#
# Read this before changing anything below, because the distinction is
# the difference between a session that completes and a session that
# vanishes half-captured.
#
# `setsid nohup CMD </dev/null &` puts CMD in a NEW session with a new
# process group and no controlling terminal.  That buys exactly two
# things: a signal sent to THIS shell's process group (an interactive
# Ctrl-C, a `kill -- -$$`) does not reach CMD, and CMD keeps running
# after the script that started it returns.
#
# It does NOT make CMD survive teardown of the whole process TREE.  A
# harness that reaps every descendant of the shell it spawned -- by
# cgroup, by session leader, or by walking /proc -- takes CMD with it
# regardless of how it was detached.  Nothing a child process can do to
# itself confers durability; durability comes only from being owned by
# something that outlives the harness.
#
# So there are exactly two honest ways to run this pipeline:
#
#   1. ONE ORCHESTRATION.  Bring the display up, launch the game, drive
#      the whole session and take the final commit inside a SINGLE
#      foreground run.  The X server and the game are then children of
#      that run and live exactly as long as it does, which is long
#      enough because the session ends inside the game with Save & Quit.
#      This is the default and it needs no host privileges.
#
#   2. A HOST-SUPERVISED SURFACE.  Have something outside the harness
#      own the X server -- the provisioned supervisor units this file
#      integrates with below, or an equivalent service -- so the display
#      persists across separate invocations.  The GAME still belongs to
#      whoever launched it; a supervised display makes re-attaching to a
#      surviving instance possible, it does not make the game immortal.
#
# Every comment in this file describes which of the two it is relying
# on.  No comment claims a lifetime that setsid cannot deliver.
# ---------------------------------------------------------------------

# The provisioned durable X surface, if the host has one.
#
# The supervisor unit file and the two program scripts are installed by
# host provisioning, NOT by this repository, so their presence is
# detected and never assumed.  They serve display :99 at
# 1920x1080x24 -- see PLAYTHROUGH_SUPERVISED_DISPLAY_NUM below, which is
# why a clone offset by CLONE_INDEX cannot use them.
export PLAYTHROUGH_SUPERVISED_X_CONF="\
/etc/supervisor/conf.d/playthrough-x.conf"
export PLAYTHROUGH_SUPERVISED_X_UNITS="\
playthrough-xvfb playthrough-openbox"
export PLAYTHROUGH_SUPERVISED_DISPLAY_NUM=99

# playthrough_supervised_x_serves_display
#   True when the provisioned durable service exists, is drivable, and
#   serves THIS run's contracted display.
#
#   The unit scripts hard-code `Xvfb :99` and `DISPLAY=:99`, so they can
#   only ever serve the unoffset display.  A clone running with
#   CLONE_INDEX set is on :(99 + index) and must bring up its own
#   server; saying so here is what keeps a parallel clone from waiting
#   on a surface that will never appear.
playthrough_supervised_x_serves_display() {
    [ -f "${PLAYTHROUGH_SUPERVISED_X_CONF}" ] || return 1
    command -v supervisorctl >/dev/null 2>&1 || return 1
    [ "${PLAYTHROUGH_DISPLAY_NUM}" \
        -eq "${PLAYTHROUGH_SUPERVISED_DISPLAY_NUM}" ] || return 1
    return 0
}

# playthrough_supervised_x_hint
#   The actionable instruction for an operator who needs a display that
#   outlives a single invocation.  Printed instead of a false promise.
playthrough_supervised_x_hint() {
    if playthrough_supervised_x_serves_display; then
        playthrough_log "for a display that outlives this" \
            "invocation, start the provisioned durable service" \
            "first: supervisorctl start" \
            "${PLAYTHROUGH_SUPERVISED_X_UNITS} (or" \
            "PLAYTHROUGH_USE_SUPERVISED_X=1 to have this script do" \
            "it), then re-run.  Note it starts Xvfb WITHOUT -auth."
        return 0
    fi
    if [ -f "${PLAYTHROUGH_SUPERVISED_X_CONF}" ] &&
       [ "${PLAYTHROUGH_DISPLAY_NUM}" \
            -ne "${PLAYTHROUGH_SUPERVISED_DISPLAY_NUM}" ]; then
        playthrough_log "this host has a durable X service, but it" \
            "serves only :${PLAYTHROUGH_SUPERVISED_DISPLAY_NUM} and" \
            "this run is on ${PLAYTHROUGH_DISPLAY}" \
            "(CLONE_INDEX=${PLAYTHROUGH_CLONE_INDEX}), so it cannot" \
            "be used here.  Drive launch and session in ONE run."
        return 0
    fi
    playthrough_log "this host has no durable X service" \
        "(${PLAYTHROUGH_SUPERVISED_X_CONF} is absent), so the" \
        "display below lives exactly as long as this shell's" \
        "process tree.  Drive the launch and the whole capture" \
        "session inside ONE run, or install a supervised Xvfb that" \
        "serves ${PLAYTHROUGH_DISPLAY} at ${PLAYTHROUGH_SCREEN}."
    return 0
}

# playthrough_start_supervised_x
#   Ask the provisioned durable service for the display.  Returns 0 only
#   when the display is genuinely answering afterwards.
#
#   OPT-IN, and deliberately so.  The provisioned units start
#   `Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp` with NO -auth, so
#   the display they provide has no access control -- and
#   playthrough_assert_x_access_control refuses such a display for a
#   recorded session, because pixels any local account could have
#   painted are not evidence.  Starting it by default would occupy the
#   display with a server this pipeline then has to refuse, with no way
#   back; so it happens only when the operator asks for it with
#   PLAYTHROUGH_USE_SUPERVISED_X=1, and the trade is stated rather than
#   hidden.  A durable display that is ALREADY answering is a different
#   case and is simply reused, exactly as any externally managed server
#   is.
playthrough_start_supervised_x() {
    playthrough_supervised_x_serves_display || return 1
    # supervisorctl needs the daemon; on a freshly started host the
    # socket may not be answering yet even though the unit files are
    # installed.  One bounded attempt to start it, then give up and let
    # the caller fall back -- this function never blocks the pipeline.
    if ! supervisorctl status >/dev/null 2>&1; then
        if command -v supervisord >/dev/null 2>&1; then
            playthrough_log "supervisord is not answering; starting" \
                "it so the durable X units can be brought up"
            supervisord >/dev/null 2>&1 || true
            sleep 1
        fi
    fi
    if ! supervisorctl status >/dev/null 2>&1; then
        playthrough_warn "supervisorctl cannot reach supervisord," \
            "so the provisioned durable X service is unavailable"
        return 1
    fi
    playthrough_log "starting the provisioned durable X service" \
        "(${PLAYTHROUGH_SUPERVISED_X_UNITS}) on" \
        "${PLAYTHROUGH_DISPLAY}"
    # Word splitting is intended: the variable holds a unit list.
    # shellcheck disable=SC2086
    supervisorctl start ${PLAYTHROUGH_SUPERVISED_X_UNITS} \
        >/dev/null 2>&1 || true
    if playthrough_wait_for_display 30; then
        playthrough_warn "using the provisioned durable display." \
            "It is started WITHOUT -auth, so it has no access" \
            "control and playthrough_assert_x_access_control will" \
            "refuse it unless PLAYTHROUGH_ALLOW_UNAUTHENTICATED_X=1." \
            "Frames captured from an open display are not evidence" \
            "of an unobserved session."
        return 0
    fi
    return 1
}

# playthrough_start_xvfb
#   Bring up the headless X server ONLY if the display is not already
#   answering, so an externally managed server -- the provisioned
#   durable service, a container sidecar -- is left strictly alone.
#
#   THE DURABLE X SURFACE IS AN EXTERNALLY SUPERVISED ONE, NOT THIS.
#   A supervised sidecar -- a process manager or container that owns
#   Xvfb and restarts it -- becomes the surface every stage shares, and
#   it is the only owner that RESTARTS the server, which is why it is
#   preferred whenever one answers and why this function is a no-op
#   whenever one is present.
#
#   Order: reuse an answering display; then the provisioned durable
#   service when the operator has asked for it; then a supervisor
#   program this file knows about; then this pipeline's own
#   authenticated server, whose lifetime is this shell's process tree
#   and which says so.  See PROCESS LIFETIME above.
#
#   The server started here is the fallback for a host without any of
#   those.  It is spawned with the full detachment idiom -- `setsid
#   nohup` puts it in its own session with no controlling terminal, so a
#   signal sent to the CALLING shell's process group, which is what an
#   outer call that times out delivers, does not reach it -- and its
#   liveness is verified rather than assumed.
#
#   -auth is as load-bearing as -nolisten tcp, and for the same reason
#   in a different direction: -nolisten tcp closes the network socket,
#   -auth closes the local one.  Without it EVERY account on the host
#   can read the screen this pipeline is photographing and inject
#   keystrokes into the session -- which breaks the
#   one-keystroke-per-frame invariant and the no-fabrication rule at the
#   same time, and leaves no trace in any artifact.  Measured on this
#   host: with -auth, a client with no cookie is refused even when it
#   runs as root; without it, an unprivileged account captured the whole
#   1920x1080 root window.
playthrough_start_xvfb() {
    if playthrough_display_ready; then
        return 0
    fi
    # THE DURABLE SURFACE FIRST, in the order the operator asked for.
    # A provisioned durable service is the only owner that RESTARTS the
    # server, so it is preferred whenever it is available or demanded;
    # this pipeline's own server is the fallback for a host without one.
    if [ "${PLAYTHROUGH_USE_SUPERVISED_X:-0}" = "1" ]; then
        if playthrough_start_supervised_x; then
            return 0
        fi
        playthrough_warn "PLAYTHROUGH_USE_SUPERVISED_X=1 but the" \
            "provisioned durable X service could not serve" \
            "${PLAYTHROUGH_DISPLAY}; falling back to this" \
            "pipeline's own server"
    fi
    if playthrough_supervisor_start \
           "${PLAYTHROUGH_SUPERVISOR_XVFB}"; then
        playthrough_log "the supervisor owns" \
            "${PLAYTHROUGH_SUPERVISOR_XVFB}; waiting for" \
            "${PLAYTHROUGH_DISPLAY}"
        playthrough_wait_for_display 30 && return 0
        playthrough_warn "the supervisor reported" \
            "${PLAYTHROUGH_SUPERVISOR_XVFB} running but nothing is" \
            "answering on ${PLAYTHROUGH_DISPLAY}; starting our own"
    fi
    if [ "${PLAYTHROUGH_REQUIRE_DURABLE_X:-0}" = "1" ]; then
        playthrough_supervised_x_hint
        playthrough_die "PLAYTHROUGH_REQUIRE_DURABLE_X=1 and no" \
            "durable X surface is answering on" \
            "${PLAYTHROUGH_DISPLAY}.  Refusing to start a server" \
            "whose lifetime is this shell's process tree, because" \
            "you asked for one that is not."
        return 1
    fi
    playthrough_supervised_x_hint
    playthrough_require_tools Xvfb xdpyinfo || return 1
    playthrough_ensure_xauth || return 1
    mkdir -p /tmp/.X11-unix 2>/dev/null || true
    playthrough_secure_truncate "${PLAYTHROUGH_XVFB_LOG}" || return 1
    playthrough_log "starting Xvfb on ${PLAYTHROUGH_DISPLAY} at" \
        "${PLAYTHROUGH_SCREEN}, authenticated with" \
        "${XAUTHORITY:-${PLAYTHROUGH_XAUTHORITY}}; its lifetime is" \
        "this shell's process tree"
    # -auth is as load-bearing as -nolisten tcp: one closes the network
    # socket, the other the local one.  playthrough_spawn_detached is
    # what makes the server survive a signal aimed at this shell AND
    # proves it is alive before returning.
    playthrough_spawn_detached "Xvfb ${PLAYTHROUGH_DISPLAY}" \
        "${PLAYTHROUGH_XVFB_PIDFILE}" "${PLAYTHROUGH_XVFB_LOG}" -- \
        Xvfb "${PLAYTHROUGH_DISPLAY}" \
        -screen 0 "${PLAYTHROUGH_SCREEN}" -nolisten tcp \
        -auth "${XAUTHORITY:-${PLAYTHROUGH_XAUTHORITY}}" || return 1
    playthrough_wait_for_display 30
}

# playthrough_assert_x_access_control
#   Prove, by trying it, that a client without the cookie CANNOT reach
#   this display.
#
#   A positive check ("we can connect") says nothing about who else can,
#   so this is deliberately a NEGATIVE check: it runs xdpyinfo with an
#   empty authority file and requires that to FAIL.  If it succeeds, the
#   display is open to every local account and the capture cannot be
#   claimed to be unobserved or uninjected, so the default is to refuse
#   to continue.  PLAYTHROUGH_ALLOW_UNAUTHENTICATED_X=1 downgrades it to
#   a loud warning for a display this pipeline did not start and cannot
#   restart; it must never be set for a recorded session.
playthrough_assert_x_access_control() {
    if ! playthrough_display_ready; then
        playthrough_die "no X server on ${PLAYTHROUGH_DISPLAY} to" \
            "check the access control of"
        return 1
    fi
    if ! env XAUTHORITY=/dev/null xdpyinfo \
            -display "${PLAYTHROUGH_DISPLAY}" >/dev/null 2>&1; then
        return 0
    fi
    if [ "${PLAYTHROUGH_ALLOW_UNAUTHENTICATED_X:-0}" = "1" ]; then
        playthrough_warn "${PLAYTHROUGH_DISPLAY} accepts clients" \
            "with no cookie, so any local account can read the" \
            "screen being captured and send keystrokes into the" \
            "session.  Continuing only because" \
            "PLAYTHROUGH_ALLOW_UNAUTHENTICATED_X=1, which holds the" \
            "trust state at diagnostic: no frame this run captures can" \
            "join the record, because a capture launch and a" \
            "production capture both refuse while it is set."
        return 0
    fi
    playthrough_die "${PLAYTHROUGH_DISPLAY} has no access control: a" \
        "client with an empty authority file connected to it." \
        "Every local account can therefore read the screen this" \
        "pipeline captures and inject keystrokes into the game." \
        "This server was not started by this pipeline -- stop it and" \
        "let playthrough_start_xvfb start an authenticated one (it" \
        "passes -auth with a fresh cookie), or set" \
        "PLAYTHROUGH_ALLOW_UNAUTHENTICATED_X=1 to accept the risk" \
        "explicitly for a diagnostic run."
    return 1
}

# playthrough_wm_ready
#   True when a window manager owns the contracted display.
playthrough_wm_ready() {
    command -v xprop >/dev/null 2>&1 || return 1
    command -v grep >/dev/null 2>&1 || return 1
    xprop -root -display "${PLAYTHROUGH_DISPLAY}" \
        _NET_SUPPORTING_WM_CHECK 2>/dev/null |
        grep -q 'window id'
}

# playthrough_start_wm
#   Start openbox only if no window manager is present.  A bare X
#   server has no focus model, and xdotool key delivery to an
#   unfocused window is unreliable, so the WM is load-bearing for
#   one-keystroke-per-frame capture rather than cosmetic.
#
#   The same detachment note as playthrough_start_xvfb applies.  A
#   window manager already owning the display -- the provisioned durable
#   openbox unit, or one started by an earlier run in the same session
#   -- is reused rather than duplicated and is the durable arrangement;
#   a configured supervisor is preferred next; and the instance started
#   here is detached from the calling shell's process group with its
#   liveness verified, which gives it the same lifetime as the server
#   above: this shell's process tree, and nothing more.  See PROCESS
#   LIFETIME.
playthrough_start_wm() {
    playthrough_require_tools xprop grep || return 1
    if playthrough_wm_ready; then
        return 0
    fi
    if playthrough_supervisor_start \
           "${PLAYTHROUGH_SUPERVISOR_WM}"; then
        local settle=0
        while [ "${settle}" -lt 40 ]; do
            if playthrough_wm_ready; then
                playthrough_log "the supervisor owns" \
                    "${PLAYTHROUGH_SUPERVISOR_WM}, which now owns" \
                    "${PLAYTHROUGH_DISPLAY}"
                return 0
            fi
            sleep 0.25
            settle=$(( settle + 1 ))
        done
        playthrough_warn "the supervisor reported" \
            "${PLAYTHROUGH_SUPERVISOR_WM} running but no window" \
            "manager owns ${PLAYTHROUGH_DISPLAY}; starting our own"
    fi
    playthrough_require_tools openbox xprop || return 1
    playthrough_secure_truncate "${PLAYTHROUGH_WM_LOG}" || return 1
    playthrough_log "starting openbox on ${PLAYTHROUGH_DISPLAY}"
    playthrough_spawn_detached "openbox ${PLAYTHROUGH_DISPLAY}" \
        "${PLAYTHROUGH_WM_PIDFILE}" "${PLAYTHROUGH_WM_LOG}" -- \
        env DISPLAY="${PLAYTHROUGH_DISPLAY}" \
        XAUTHORITY="${XAUTHORITY:-${PLAYTHROUGH_XAUTHORITY}}" \
        openbox || return 1
    local waited=0
    while [ "${waited}" -lt 40 ]; do
        if playthrough_wm_ready; then
            return 0
        fi
        sleep 0.25
        waited=$(( waited + 1 ))
    done
    playthrough_die "openbox did not take ownership of" \
        "${PLAYTHROUGH_DISPLAY} (log: ${PLAYTHROUGH_WM_LOG})"
    return 1
}

# playthrough_assert_display
#   Assert the root window really is the contracted geometry and
#   depth.  Capture targets the root, so a wrong size here would
#   silently produce a movie at the wrong resolution.
playthrough_assert_display() {
    playthrough_require_tools xdpyinfo awk || return 1
    playthrough_display_ready || {
        playthrough_die "no X server on ${PLAYTHROUGH_DISPLAY}"
        return 1
    }
    local info dims depth want
    info="$(xdpyinfo -display "${PLAYTHROUGH_DISPLAY}" 2>/dev/null)"
    dims="$(printf '%s\n' "${info}" |
        awk '/dimensions:/ { print $2; exit }')"
    depth="$(printf '%s\n' "${info}" |
        awk '/depth of root window:/ { print $5; exit }')"
    want="${PLAYTHROUGH_SCREEN_WIDTH}x${PLAYTHROUGH_SCREEN_HEIGHT}"
    if [ "${dims}" != "${want}" ]; then
        playthrough_die "root window is '${dims}', expected" \
            "'${want}' on ${PLAYTHROUGH_DISPLAY}"
        return 1
    fi
    if [ "${depth}" != "${PLAYTHROUGH_SCREEN_DEPTH}" ]; then
        playthrough_die "root depth is '${depth}', expected" \
            "'${PLAYTHROUGH_SCREEN_DEPTH}'"
        return 1
    fi
    return 0
}

# playthrough_headless_up
#   Bring the whole headless surface up idempotently and verify it:
#   platform support, video driver, X server, window manager, ACCESS
#   CONTROL, geometry.  This is what launch_game.sh calls before it
#   launches anything.
#
#   The access-control assertion sits deliberately BEFORE the geometry
#   check and therefore before anything is launched or captured: an open
#   display invalidates the session as evidence, so it has to be caught
#   while there is still nothing to invalidate.
#
#   CALL IT AGAIN RATHER THAN TRUSTING AN EARLIER CALL.  Every step is
#   a no-op when the thing it establishes is already there, so the
#   cost of re-asserting is one xdpyinfo and one xprop -- and on a
#   platform that can tear down a whole process tree between two
#   automation calls, re-asserting is the only thing that makes a
#   multi-call pipeline correct.  There is deliberately no cached
#   "already up" flag in this file for that reason.
playthrough_headless_up() {
    playthrough_check_platform || return 1
    playthrough_assert_video_driver || return 1
    playthrough_require_tools xdpyinfo xprop grep awk || return 1
    playthrough_start_xvfb || return 1
    playthrough_start_wm || return 1
    playthrough_assert_x_access_control || return 1
    playthrough_assert_display || return 1
    return 0
}

# playthrough_mkdirs
#   Create the artifact directories.  Called explicitly, never at
#   source time: sourcing this file must not write into the tree.
#
#   Each path is proved to resolve inside the checkout and to have no
#   symlinked component BEFORE it is created or used, and the check runs
#   top down so that a link planted at `playthrough/` is caught before
#   `playthrough/frames` is even considered.  Without this, a single
#   symlink is enough to send the userdir -- and therefore the save, the
#   config and the committed keybindings evidence -- outside the working
#   tree, where `git add` would silently find nothing to add.
playthrough_mkdirs() {
    local dir
    for dir in \
        "${PLAYTHROUGH_DIR}" \
        "${PLAYTHROUGH_FRAMES_DIR}" \
        "${PLAYTHROUGH_BUILD_DIR}" \
        "${PLAYTHROUGH_TRANSITIONS_DIR}" \
        "${PLAYTHROUGH_USERDIR}"; do
        playthrough_assert_inside "${dir}" \
            "${PLAYTHROUGH_REPO_ROOT}" "artifact directory" ||
            return 1
        playthrough_assert_no_symlink "${dir}" \
            "${PLAYTHROUGH_REPO_ROOT}" "artifact directory" ||
            return 1
        if [ ! -d "${dir}" ] && ! mkdir -p -- "${dir}"; then
            playthrough_die "cannot create ${dir}"
            return 1
        fi
    done
    return 0
}

# playthrough_acquire_lock NAME [TIMEOUT_SECONDS]
#   Take an exclusive advisory lock and leave its descriptor in
#   PLAYTHROUGH_LOCK_FD.
#
#   Check-and-act is the whole problem this solves.  "No game is
#   running, so start one" and "no build is running, so start one" are
#   both two operations, and two invocations that interleave between them
#   end up with two engines writing one save, or two makes writing one
#   object tree.  The lock is held by an open descriptor, so it survives
#   for as long as the shell that took it and is released by the kernel
#   even if that shell dies.
#
#   The descriptor is allocated with bash's {var} redirection rather than
#   a fixed number, so nothing in a caller collides with it, and NOT with
#   eval: there is no eval anywhere in this tree.
PLAYTHROUGH_CHILD_CLOSE_FD=""
PLAYTHROUGH_CHILD_CLOSE_BORROWED=0

playthrough_acquire_lock() {
    local name="${1-}"
    case "${name}" in
        ''|*[!a-z0-9_-]*)
            playthrough_die "'${name}' is not a usable lock name" \
                "(lowercase letters, digits, '-' and '_' only)"
            return 1
            ;;
    esac
    playthrough_validate_int "${2:-60}" "lock timeout" 0 86400 ||
        return 1
    local timeout="${PLAYTHROUGH_INT}"
    playthrough_require_tools flock || return 1
    local path="${PLAYTHROUGH_LOCK_DIR}/${name}.lock"
    playthrough_secure_file "${path}" 600 || return 1
    local fd
    if ! exec {fd}>>"${path}"; then
        playthrough_die "cannot open the '${name}' lock at ${path}"
        return 1
    fi
    if ! flock -w "${timeout}" "${fd}"; then
        exec {fd}>&-
        playthrough_die "another process has held the '${name}' lock" \
            "for more than ${timeout}s (${path}).  Two runs of this" \
            "stage over one checkout would corrupt what they share," \
            "so this one stops rather than racing it."
        return 1
    fi
    PLAYTHROUGH_LOCK_FD="${fd}"
    return 0
}

# playthrough_child_close_fd / playthrough_child_close_done
#   Make it safe to detach a long-lived child while a lock is held.
#
#   A LOCK IS HELD BY AN OPEN DESCRIPTOR, AND A CHILD INHERITS IT.  That
#   is the whole of the problem, and it is not theoretical -- it was
#   measured here: the detached engine inherited the 'session' lock's
#   descriptor and therefore held the lock for its entire lifetime, so a
#   second `launch_game.sh launch` (the ordinary way a caller
#   re-attaches to a running instance) blocked for the full timeout and
#   then failed, reporting a concurrent launch that did not exist.
#
#   The critical section genuinely has to span the spawn -- otherwise two
#   runs could both decide to start an engine -- so releasing the lock
#   early is not the fix.  The fix is that the CHILD does not get the
#   descriptor: bash's `{var}>&-` closes it for that one command, which
#   leaves the parent still holding the lock until it releases it
#   deliberately.
#
#   `{var}>&-` is an "ambiguous redirect" when var is empty, so a
#   descriptor is BORROWED from /dev/null when no lock is held.  That
#   keeps the spawn a single code path instead of two nearly identical
#   ones that would drift apart.
#
#   Usage:
#       playthrough_child_close_fd
#       setsid nohup CMD ... {PLAYTHROUGH_CHILD_CLOSE_FD}>&- &
#       spawned="$!"
#       playthrough_child_close_done
playthrough_child_close_fd() {
    PLAYTHROUGH_CHILD_CLOSE_FD="${PLAYTHROUGH_LOCK_FD:-}"
    PLAYTHROUGH_CHILD_CLOSE_BORROWED=0
    case "${PLAYTHROUGH_CHILD_CLOSE_FD}" in
        ''|*[!0-9]*)
            if ! exec {PLAYTHROUGH_CHILD_CLOSE_FD}</dev/null; then
                playthrough_die "cannot open a descriptor to withhold" \
                    "from a detached child"
                return 1
            fi
            PLAYTHROUGH_CHILD_CLOSE_BORROWED=1
            ;;
    esac
    return 0
}

playthrough_child_close_done() {
    if [ "${PLAYTHROUGH_CHILD_CLOSE_BORROWED:-0}" = "1" ]; then
        case "${PLAYTHROUGH_CHILD_CLOSE_FD:-}" in
            ''|*[!0-9]*) ;;
            *) exec {PLAYTHROUGH_CHILD_CLOSE_FD}>&- 2>/dev/null ;;
        esac
    fi
    PLAYTHROUGH_CHILD_CLOSE_FD=""
    PLAYTHROUGH_CHILD_CLOSE_BORROWED=0
    return 0
}

# playthrough_release_lock [FD]
#   Drop a lock taken above.  Defaults to the most recent one; a caller
#   holding two passes the descriptor it saved.
playthrough_release_lock() {
    local fd="${1:-${PLAYTHROUGH_LOCK_FD:-}}"
    case "${fd}" in
        ''|*[!0-9]*) return 0 ;;
    esac
    flock -u "${fd}" 2>/dev/null || true
    exec {fd}>&- 2>/dev/null || true
    if [ "${fd}" = "${PLAYTHROUGH_LOCK_FD:-}" ]; then
        PLAYTHROUGH_LOCK_FD=""
    fi
    return 0
}

# playthrough_os_release KEY
#   Read one KEY=value out of /etc/os-release, unquoted, or print
#   nothing.  The file is PARSED rather than sourced: sourcing executes
#   it, and a check whose whole purpose is to reduce risk should not add
#   an execution path of its own.  KEY is restricted to the shape the
#   specification uses, so nothing can be smuggled into the expression.
playthrough_os_release() {
    case "${1-}" in
        ''|*[!A-Z_]*) return 1 ;;
    esac
    [ -r /etc/os-release ] || return 0
    sed -n "s/^${1}=//p" /etc/os-release |
        head -n 1 |
        tr -d '\042\047'
}

# playthrough_check_platform
#   Report -- once -- whether this host is still receiving security
#   fixes, because a version number is only as good as the archive still
#   publishing updates for it.
#
#   ImageMagick, ffmpeg and the Xorg/Xvfb stack all parse
#   untrusted-shaped input, and on an end-of-life release their known
#   issues stay unfixed by definition however current `dpkg-query`
#   looks.  This is a WARNING by default because the pipeline must still
#   be runnable for diagnosis on whatever host it finds itself on;
#   PLAYTHROUGH_REQUIRE_SUPPORTED_PLATFORM=1 makes it a hard failure,
#   which is the right setting for a recorded session.
#
#   The table below is dated: end-of-life dates are facts about the
#   world, not about this repository, so it is small on purpose, states
#   when it was compiled, and treats anything it does not know as
#   unverified rather than as supported.
playthrough_check_platform() {
    if [ -n "${PLAYTHROUGH_PLATFORM_CHECKED:-}" ]; then
        [ "${PLAYTHROUGH_PLATFORM_SUPPORTED}" != "no" ] && return 0
        [ "${PLAYTHROUGH_REQUIRE_SUPPORTED_PLATFORM:-0}" != "1" ] &&
            return 0
        return 1
    fi
    local id version pretty eol=""
    id="$(playthrough_os_release ID)"
    version="$(playthrough_os_release VERSION_ID)"
    pretty="$(playthrough_os_release PRETTY_NAME)"
    # Compiled 2026-08-03 from the distributions' own published
    # schedules.  Recheck it when this pipeline is next provisioned.
    case "${id}:${version}" in
        ubuntu:26.04) eol="2031-04" ;;
        ubuntu:24.04) eol="2029-04" ;;
        ubuntu:25.10) eol="2026-07-09" ;;
        ubuntu:25.04) eol="2026-01-15" ;;
        ubuntu:24.10) eol="2025-07-10" ;;
        debian:13) eol="2030-06" ;;
        debian:12) eol="2028-06" ;;
    esac
    export PLAYTHROUGH_PLATFORM="${pretty:-${id:-unknown}}"
    export PLAYTHROUGH_PLATFORM_EOL="${eol:-unknown}"
    export PLAYTHROUGH_PLATFORM_CHECKED=1
    local today
    today="$(date -u +%Y-%m-%d)"
    if [ -z "${eol}" ]; then
        export PLAYTHROUGH_PLATFORM_SUPPORTED="unverified"
        playthrough_warn "cannot tell whether" \
            "'${PLAYTHROUGH_PLATFORM}' is still receiving security" \
            "updates; confirm it is in support and fully patched" \
            "before recording a session"
        return 0
    fi
    # Both sides are ISO-8601, so a lexical comparison is a date
    # comparison; a table entry of "2031-04" compares as "2031-04" <
    # "2031-04-01", which errs towards warning early rather than late.
    if [ "${today}" '>' "${eol}" ]; then
        export PLAYTHROUGH_PLATFORM_SUPPORTED="no"
        playthrough_warn "'${PLAYTHROUGH_PLATFORM}' reached end of" \
            "life on ${eol}, so its ImageMagick, ffmpeg and" \
            "Xorg/Xvfb packages receive no further security fixes." \
            "All three parse untrusted-shaped input in this" \
            "pipeline.  Move to a supported release (Ubuntu 26.04" \
            "LTS or later) and apply outstanding updates before" \
            "recording a session; set" \
            "PLAYTHROUGH_REQUIRE_SUPPORTED_PLATFORM=1 to make this" \
            "a hard failure."
        if [ "${PLAYTHROUGH_REQUIRE_SUPPORTED_PLATFORM:-0}" = "1" ]; then
            playthrough_die "refusing to run on the end-of-life" \
                "platform '${PLAYTHROUGH_PLATFORM}' because" \
                "PLAYTHROUGH_REQUIRE_SUPPORTED_PLATFORM=1"
            return 1
        fi
        return 0
    fi
    export PLAYTHROUGH_PLATFORM_SUPPORTED="yes"
    return 0
}

# playthrough_python [args ...]
#   Run the resolved interpreter, so no sibling has to rediscover it.
#   The interpreter was verified at source time; this wrapper exists so
#   that no caller re-searches PATH and finds a different one.
playthrough_python() {
    "${PLAYTHROUGH_PYTHON}" "$@"
}

# playthrough_env_summary
#   Print the resolved contract on stdout.  Used by the direct
#   execution path below and worth logging at the head of a session,
#   because it is the record of what the capture actually ran under.
playthrough_env_summary() {
    # Resolve the platform verdict so the record carries it.  It is
    # memoised and warns at most once, and a strict-mode refusal is the
    # caller's business rather than the summary's, hence `|| true`.
    # The pairs are collected in an ARRAY rather than written straight
    # into printf's argument list, and that is a correctness decision
    # rather than a style one.  A continued argument list needs a
    # trailing backslash on every line, and a single missing one does
    # not fail: bash ends the printf there and parses the next line as a
    # command of its own, so the report silently stops early and the
    # dropped fields -- XAUTHORITY, IMAGEIO_FFMPEG_EXE and the platform
    # verdict among them -- read as absent rather than as unprinted.
    # `bash -n` accepts it, because nothing is syntactically wrong.
    # Inside ( ... ) no continuations are needed at all, so that failure
    # cannot happen here again.  KEEP IT THIS WAY.
    playthrough_check_platform >/dev/null 2>&1 || true
    # The trust state is recomputed here for the same reason: this is
    # the record of what a session ran under, and "diagnostic" is the
    # single most important thing it can say.  Refusing is the launch's
    # and the capture's business, not the summary's.
    playthrough_trust_refresh || true
    local _playthrough_summary_fields=(
        "DISPLAY" "${DISPLAY}"
        "SDL_VIDEODRIVER" "${SDL_VIDEODRIVER}"
        "SDL_AUDIODRIVER" "${SDL_AUDIODRIVER}"
        "LIBGL_ALWAYS_SOFTWARE" "${LIBGL_ALWAYS_SOFTWARE}"
        "XDG_RUNTIME_DIR" "${XDG_RUNTIME_DIR}"
        "XAUTHORITY" "${XAUTHORITY:-<unset>}"
        "PYTHONDONTWRITEBYTECODE" "${PYTHONDONTWRITEBYTECODE}"
        "IMAGEIO_FFMPEG_EXE" "${IMAGEIO_FFMPEG_EXE:-<unset>}"
        "PLAYTHROUGH_CLONE_INDEX" "${PLAYTHROUGH_CLONE_INDEX}"
        "PLAYTHROUGH_RUNTIME_DIR" "${PLAYTHROUGH_RUNTIME_DIR}"
        "PLAYTHROUGH_XAUTHORITY_ORIGIN"
        "${PLAYTHROUGH_XAUTHORITY_ORIGIN}"
        "PLAYTHROUGH_PLATFORM" "${PLAYTHROUGH_PLATFORM:-<unchecked>}"
        "PLAYTHROUGH_PLATFORM_SUPPORTED"
        "${PLAYTHROUGH_PLATFORM_SUPPORTED:-<unchecked>}"
        "PLAYTHROUGH_SCREEN" "${PLAYTHROUGH_SCREEN}"
        "PLAYTHROUGH_WINDOW_CLASS" "${PLAYTHROUGH_WINDOW_CLASS}"
        "PLAYTHROUGH_TILESET" "${PLAYTHROUGH_TILESET}"
        "PLAYTHROUGH_SIDEBAR_LAYOUT" "${PLAYTHROUGH_SIDEBAR_LAYOUT}"
        "PLAYTHROUGH_SIDEBAR_CELLS" "${PLAYTHROUGH_SIDEBAR_CELLS}"
        "PLAYTHROUGH_REPO_ROOT" "${PLAYTHROUGH_REPO_ROOT}"
        "PLAYTHROUGH_DIR" "${PLAYTHROUGH_DIR}"
        "PLAYTHROUGH_FRAMES_DIR" "${PLAYTHROUGH_FRAMES_DIR}"
        "PLAYTHROUGH_BUILD_DIR" "${PLAYTHROUGH_BUILD_DIR}"
        "PLAYTHROUGH_TRANSITIONS_DIR" "${PLAYTHROUGH_TRANSITIONS_DIR}"
        "PLAYTHROUGH_USERDIR" "${PLAYTHROUGH_USERDIR}"
        "PLAYTHROUGH_USERDIR_ARG" "${PLAYTHROUGH_USERDIR_ARG}"
        "PLAYTHROUGH_MANIFEST" "${PLAYTHROUGH_MANIFEST}"
        "PLAYTHROUGH_OBSERVATIONS" "${PLAYTHROUGH_OBSERVATIONS}"
        "PLAYTHROUGH_DATE_AUDIT" "${PLAYTHROUGH_DATE_AUDIT}"
        "PLAYTHROUGH_TIMELINE" "${PLAYTHROUGH_TIMELINE}"
        "PLAYTHROUGH_MOVIE" "${PLAYTHROUGH_MOVIE}"
        "PLAYTHROUGH_MOVIE_CC" "${PLAYTHROUGH_MOVIE_CC}"
        "PLAYTHROUGH_SUPERVISOR_XVFB" "${PLAYTHROUGH_SUPERVISOR_XVFB}"
        "PLAYTHROUGH_SUPERVISOR_WM" "${PLAYTHROUGH_SUPERVISOR_WM}"
        "PLAYTHROUGH_PYTHON" "${PLAYTHROUGH_PYTHON}"
        "PLAYTHROUGH_PYTHON_VERSION"
        "${PLAYTHROUGH_PYTHON_VERSION:-<unknown>}"
        "PLAYTHROUGH_PYTHON_ABI" "${PLAYTHROUGH_PYTHON_ABI}"
        "PLAYTHROUGH_TRUST_STATE" "${PLAYTHROUGH_TRUST_STATE}"
        "PLAYTHROUGH_TRUST_BYPASSES"
        "${PLAYTHROUGH_TRUST_BYPASSES:-<none>}"
    )
    printf '%s\n' "playthrough environment contract"
    printf '  %-26s %s\n' "${_playthrough_summary_fields[@]}"
}

# ---------------------------------------------------------------------
# THE ENCODER: pin imageio and MoviePy to the system ffmpeg
#
# imageio-ffmpeg ships a static ffmpeg inside its wheel -- 7.0.2 in the
# pinned 0.6.0, which is the newest release of that package -- and
# get_ffmpeg_exe() prefers that bundled binary over anything on PATH
# unless IMAGEIO_FFMPEG_EXE says otherwise.  So the encoder that would
# actually run is one no apt inventory lists and no Python advisory
# check can see, and it is older than the one this host maintains.
#
# Exporting the verified system ffmpeg here is the supported override
# and the only place it is set, so the render stage cannot drift from
# the capture stage.  A caller's own IMAGEIO_FFMPEG_EXE is respected --
# it may legitimately point at a newer build -- but it is verified
# first, exactly like the interpreter.
# ---------------------------------------------------------------------
if [ -n "${IMAGEIO_FFMPEG_EXE:-}" ]; then
    if ! playthrough_verify_executable \
            "${IMAGEIO_FFMPEG_EXE}" "IMAGEIO_FFMPEG_EXE"; then
        playthrough_warn "the inherited IMAGEIO_FFMPEG_EXE" \
            "'${IMAGEIO_FFMPEG_EXE}' did not verify; replacing it" \
            "with the system ffmpeg"
        unset IMAGEIO_FFMPEG_EXE
    fi
fi
if [ -z "${IMAGEIO_FFMPEG_EXE:-}" ]; then
    if playthrough_resolve_tool ffmpeg; then
        export IMAGEIO_FFMPEG_EXE="${PLAYTHROUGH_BIN_FFMPEG}"
    else
        playthrough_warn "no verified system ffmpeg was found, so" \
            "imageio and MoviePy would fall back to the unpatched" \
            "static binary bundled in the imageio-ffmpeg wheel." \
            "Install the ffmpeg package listed in" \
            "playthrough/tooling/requirements.txt before rendering."
    fi
fi

# ---------------------------------------------------------------------
# Final guard, then done.
#
# The assertion is repeated here at source time so that a contract
# which somehow does not carry x11 can never leave this file quietly.
# Fail loudly, never silently -- the whole point of banning the dummy
# video backend is that its symptom is invisibility.
# ---------------------------------------------------------------------
if ! playthrough_assert_video_driver; then
    return 1 2>/dev/null || exit 1
fi

# The trust state is published at source time so that every consumer --
# including the Python stages, which read it out of the environment --
# starts from a computed answer rather than an absent one.  A bypass is
# NOT fatal here: sourcing this file is not producing evidence, and the
# refusal belongs to the launch and the capture, which recompute it.
playthrough_trust_refresh || true

# THE SUMMARY'S STATUS IS THE DIRECT RUN'S STATUS.
#
# `bash playthrough/tooling/env.sh` exists to PRINT the contract, so a
# summary that could not be written is a failed run and has to say so
# with its exit code.  The status is carried across the unsets below
# rather than being taken from them, because `unset` always succeeds:
# reporting whatever the last one returned is how a broken summary used
# to exit 0 while the error sat in the output.
_playthrough_summary_status=0
if [ "${_playthrough_executed}" = "1" ]; then
    playthrough_env_summary || _playthrough_summary_status="$?"
    if [ "${_playthrough_summary_status}" -ne 0 ]; then
        playthrough_warn "the environment summary could not be" \
            "written in full (status ${_playthrough_summary_status});" \
            "the contract itself is unaffected, but this run's record" \
            "of it is incomplete"
    fi
fi

# Leave no scratch names behind in the caller's shell.  Only the
# exported PLAYTHROUGH_* set, the six environment variables and the
# helper functions are part of this file's contract.
#
# _playthrough_euid is the one underscore-prefixed function that
# survives the source: the ownership checks in playthrough_secure_dir
# and playthrough_secure_file call it, so it has to outlive this file
# just as they do.  The underscore marks it as internal.
unset _playthrough_script_dir
unset _playthrough_repo_root _playthrough_index _playthrough_index_raw
unset _playthrough_suffix _playthrough_runtime_dir _playthrough_python
unset _playthrough_kbjson _playthrough_display_base
unset _playthrough_scratch_dir _playthrough_python_version

if [ "${_playthrough_executed}" = "1" ]; then
    _playthrough_status="${_playthrough_summary_status}"
    unset _playthrough_executed _playthrough_summary_status
    exit "${_playthrough_status}"
fi
unset _playthrough_executed _playthrough_summary_status
