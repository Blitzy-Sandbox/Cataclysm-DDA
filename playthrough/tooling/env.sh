#!/usr/bin/env bash
# shellcheck shell=bash
# shellcheck disable=SC2317
#
# playthrough/tooling/env.sh -- the SINGLE definition of the headless
# render environment and the artifact layout for the Cataclysm-DDA
# playthrough capture pipeline, so no two stages can drift over the
# display, the video driver or a path.
#
#     . playthrough/tooling/env.sh
#
# The shell entry points in this folder SOURCE it; the Python modules
# CONSUME the environment it exports rather than sourcing shell, and
# fall back to the layout defaults when a variable is absent.  It
# locates itself and the checkout through BASH_SOURCE, so it may be
# sourced from any directory -- but the STAGES and the ENGINE must run
# with the checkout as their working directory, which is a source-level
# requirement rather than a style preference (see WORKING DIRECTORY
# below for the citations).  Executing this file instead prints the
# resolved contract and exports nothing; re-sourcing is harmless.
#
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
# scripts publish there.  Requires bash: BASH_SOURCE, arrays and
# `local` are all used below.
#
# playthrough/README.md documents the contract for an operator -- every
# variable, the re-run procedure and the artifact inventory.
# ---------------------------------------------------------------------
# THE SECURITY CONTRACT THIS FILE OWNS
#
# The pipeline runs unattended on a host whose /tmp is world-writable
# without the sticky bit, and its output is evidence, whose whole value
# is that it was not tampered with.  Five properties are established
# here, once, so no sibling script has to remember them:
#
#   1. ONE PRIVATE RUNTIME ROOT for every diagnostic, log, pid file,
#      lock and withdrawn frame: mode 0700, created under a restrictive
#      umask, with type, owner and mode verified before use
#      (playthrough_secure_dir).
#   2. THE DISPLAY IS AUTHENTICATED.  Xvfb runs with -auth and a fresh
#      128-bit MIT-MAGIC-COOKIE-1, and a client without the cookie is
#      asserted to be refused: an open X server lets any local account
#      read the screen and inject keystrokes, which would defeat both
#      the one-keystroke-per-frame invariant and the no-fabrication rule.
#   3. EXECUTABLES ARE VERIFIED, NOT MERELY FOUND -- ownership and
#      group/world-writability, on the binary and on every directory
#      above it (playthrough_verify_executable).
#   4. PATHS ARE CONTAINED: artifact directories are proved to resolve
#      inside the checkout with no symlinked component
#      (playthrough_assert_inside, playthrough_assert_no_symlink).
#   5. NUMBERS FROM THE ENVIRONMENT ARE VALIDATED BEFORE ARITHMETIC,
#      because bash evaluates command substitution inside an arithmetic
#      expansion: an unvalidated timeout is code execution, not a number
#      (playthrough_validate_int).
#
# The diagnosis escape hatches are enumerated in
# PLAYTHROUGH_TRUST_BYPASS_VARS below.  Each is off by default and
# ENFORCED rather than deprecated: setting any one moves
# PLAYTHROUGH_TRUST_STATE to "diagnostic", and a production launch or
# capture then REFUSES to run, because a warning telling an operator not
# to record a session is not a control.  See THE TRUST STATE beside
# playthrough_trust_refresh.
# ---------------------------------------------------------------------
# PROCESS LIFETIME -- THE HONEST CONTRACT
#
# `setsid nohup ... </dev/null &` insulates a started X server or game
# from signals aimed at this shell and lets it outlive the calling
# script.  That is ALL it does: it does NOT survive teardown of the
# calling shell's process TREE.  The three-tier preference this file
# applies -- a durable supervisor, then verified detachment, then
# re-assertion at the point of use -- and the two honest ways to run a
# session are documented at PROCESS LIFETIME beside
# playthrough_start_xvfb.  PLAYTHROUGH_USE_SUPERVISED_X=1 uses the
# host's durable service instead (it has no -auth);
# PLAYTHROUGH_REQUIRE_DURABLE_X=1 refuses a display whose lifetime is
# this process tree.  For every caller the consequence is one line:
# treat playthrough_headless_up as something to call again, not
# something already done.  It is idempotent and cheap by design.
# ---------------------------------------------------------------------
# WHY THIS FILE DOES NOT `set -euo pipefail`  (deliberate -- please do
# not "fix" it)
#
# Shell options set at the top level of a SOURCED file are imposed on
# the calling shell and stay there after the source returns, so a stage
# would silently inherit errexit, nounset and pipefail and change
# behaviour, and an interactive shell would start exiting on the next
# failed command.  Every other *.sh here is executed rather than sourced
# and sets those options itself.  Where an option is genuinely needed in
# this file it is set inside a function, which scopes it.
#
# The two shellcheck directives above are the only suppressions: SC2317
# fires on the `return 1 2>/dev/null || exit 1` bail idiom, which
# ShellCheck cannot model because `return` succeeds when sourced and
# fails when executed, so exactly one arm runs and neither is dead code.
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
# Small reporting helpers, defined first so everything below can use them.
# ---------------------------------------------------------------------
# playthrough_redact TEXT
#   Strip host locations out of one diagnostic line.
PLAYTHROUGH_MAX_RECORD_TOKEN=128

# playthrough_has_control TEXT
#   True when TEXT contains a C0 control, DEL, or a C1 control.
playthrough_has_control() {
    case "${1-}" in
        *[$'\001'-$'\037']*|*$'\177'*) return 0 ;;
    esac
    case "${1-}" in
        *$'\302'[$'\200'-$'\237']*) return 0 ;;
    esac
    return 1
}

# playthrough_escape_controls TEXT
#   TEXT with every control character replaced by a visible <NN> escape.
playthrough_escape_controls() {
    # BYTES, DETERMINISTICALLY, whatever the caller's locale is.
    local LC_ALL=C
    local out="" rest="${1-}" byte second
    playthrough_has_control "${rest}" || {
        printf '%s' "${rest}"
        return 0
    }
    # One byte at a time, because the substitution has to name WHICH byte
    # it replaced; a blanket `tr -d` would delete the evidence that
    # something was there at all.
    while [ -n "${rest}" ]; do
        byte="${rest:0:1}"
        case "${byte}" in
            $'\302')
                # A C1 control is 0xC2 followed by 0x80-0x9F.
                second="${rest:1:1}"
                case "${second}" in
                    [$'\200'-$'\237'])
                        out+="$(printf '<%02X>' "'${second}")"
                        rest="${rest:2}"
                        continue
                        ;;
                esac
                ;;
            [$'\001'-$'\037']|$'\177')
                out+="$(printf '<%02X>' "'${byte}")"
                rest="${rest:1}"
                continue
                ;;
        esac
        out+="${byte}"
        rest="${rest:1}"
    done
    printf '%s' "${out}"
}

playthrough_redact() {
    local text="${1-}"
    if [ -n "${PLAYTHROUGH_REPO_ROOT:-}" ]; then
        text="${text//"${PLAYTHROUGH_REPO_ROOT}/"/}"
        text="${text//"${PLAYTHROUGH_REPO_ROOT}"/.}"
    fi
    if [ -n "${PLAYTHROUGH_RUNTIME_DIR:-}" ]; then
        text="${text//"${PLAYTHROUGH_RUNTIME_DIR}"/<runtime>}"
    fi
    # LAST, so a control character cannot be reintroduced by a
    # substitution above, and so the escaping applies to the whole
    # message rather than to the part somebody thought to guard.
    playthrough_escape_controls "${text}"
}

# playthrough_assert_record_token VALUE LABEL
#   Refuse a value that cannot safely become one line of the record.
playthrough_assert_record_token() {
    local value="${1-}"
    local label="${2:-a record value}"
    if [ -z "${value}" ]; then
        playthrough_die "${label} is empty, and an empty value cannot" \
            "identify anything the record refers to"
        return 1
    fi
    if [ "${#value}" -gt "${PLAYTHROUGH_MAX_RECORD_TOKEN}" ]; then
        playthrough_die "${label} is ${#value} characters, past the" \
            "${PLAYTHROUGH_MAX_RECORD_TOKEN}-character ceiling for a" \
            "value that becomes one line of the record:" \
            "$(playthrough_escape_controls "${value:0:64}")..."
        return 1
    fi
    if playthrough_has_control "${value}"; then
        playthrough_die "${label} carries a control character, so it" \
            "cannot be written as one line of the record without" \
            "forging or corrupting it. The value, with every control" \
            "byte shown as <NN>, is:" \
            "$(playthrough_escape_controls "${value}")"
        return 1
    fi
    return 0
}

playthrough_log() {
    printf 'playthrough: %s\n' "$(playthrough_redact "$*")" >&2
}

playthrough_warn() {
    printf 'playthrough: WARNING: %s\n' \
        "$(playthrough_redact "$*")" >&2
}

playthrough_die() {
    printf 'playthrough: FATAL: %s\n' \
        "$(playthrough_redact "$*")" >&2
    return 1
}

# ---------------------------------------------------------------------
# SECURITY PRIMITIVES
#
# Defined before anything else, because the assignments further down --
# the runtime directory, the interpreter, the cookie file -- use them at
# source time.
# ---------------------------------------------------------------------

# _playthrough_euid -- this process's effective uid, without needing a tool on
# PATH.
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

# ---------------------------------------------------------------------
# THE TRUSTED UTILITY BOOTSTRAP
# A security check is worth no more than the program that performs it.
# ---------------------------------------------------------------------

# Where a security-critical utility may come from.
PLAYTHROUGH_TRUSTED_UTIL_DIRS="/usr/bin /bin /usr/sbin /sbin"

# The utilities the checks below cannot be PERFORMED without.  All three
# are coreutils, which every platform this pipeline targets ships.
PLAYTHROUGH_TRUSTED_UTILS="stat readlink chmod"

# playthrough_trust_unverifiable REASON
#   Record that a security check could not be PERFORMED at all.
playthrough_trust_unverifiable() {
    local reason="${1-an unnamed security check could not be run}"
    local existing="${PLAYTHROUGH_TRUST_UNVERIFIED-}"
    case "${existing}" in
        *"${reason}"*) ;;
        '') existing="${reason}" ;;
        *) existing="${existing}; ${reason}" ;;
    esac
    export PLAYTHROUGH_TRUST_UNVERIFIED="${existing}"
    # This can fire at source time, before the trust helpers further down the
    # file exist -- the very first playthrough_secure_dir call is one of the
    # things the bootstrap protects.
    if command -v playthrough_trust_refresh >/dev/null 2>&1; then
        playthrough_trust_refresh >/dev/null 2>&1 || true
    else
        export PLAYTHROUGH_TRUST_STATE="diagnostic"
    fi
    return 0
}

# playthrough_trusted_util NAME
#   Print the absolute path of NAME inside the trusted directories, or return
#   1.  The name is checked against a closed vocabulary -- plain lower-case
#   letters -- so nothing resembling a path or a shell metacharacter can be
#   appended to a trusted directory here.
playthrough_trusted_util() {
    local name="${1-}"
    case "${name}" in
        ''|*[!a-z]*) return 1 ;;
    esac
    local dir candidate
    for dir in ${PLAYTHROUGH_TRUSTED_UTIL_DIRS}; do
        candidate="${dir}/${name}"
        if [ -f "${candidate}" ] && [ -x "${candidate}" ]; then
            printf '%s' "${candidate}"
            return 0
        fi
    done
    return 1
}

# _playthrough_bootstrap_utilities
#   Resolve every name in PLAYTHROUGH_TRUSTED_UTILS, verify the set with the
#   resolved `stat`, and export PLAYTHROUGH_UTIL_<NAME> plus
#   PLAYTHROUGH_UTILITY_TRUST ("trusted" or "unresolved").
_playthrough_bootstrap_utilities() {
    local name var path unresolved="" perm owner
    for name in ${PLAYTHROUGH_TRUSTED_UTILS}; do
        var="PLAYTHROUGH_UTIL_${name^^}"
        path="$(playthrough_trusted_util "${name}")" || path=""
        if [ -z "${path}" ]; then
            unresolved="${unresolved}${unresolved:+ }${name}"
        fi
        export "${var}=${path}"
    done
    if [ -n "${unresolved}" ]; then
        export PLAYTHROUGH_UTILITY_TRUST="unresolved"
        playthrough_trust_unverifiable "the security-critical \
utilities ${unresolved} are not present in \
${PLAYTHROUGH_TRUSTED_UTIL_DIRS// /, }, so no ownership, mode or \
containment check can be performed (install coreutils)"
        return 1
    fi
    for name in ${PLAYTHROUGH_TRUSTED_UTILS}; do
        var="PLAYTHROUGH_UTIL_${name^^}"
        path="${!var}"
        perm="$("${PLAYTHROUGH_UTIL_STAT}" -Lc '%a' -- "${path}" \
            2>/dev/null || true)"
        owner="$("${PLAYTHROUGH_UTIL_STAT}" -Lc '%u' -- "${path}" \
            2>/dev/null || true)"
        if [ -z "${perm}" ] || [ -z "${owner}" ]; then
            export PLAYTHROUGH_UTILITY_TRUST="unresolved"
            playthrough_trust_unverifiable "'${path}' could not be \
inspected, so the utilities the ownership and mode checks are made of \
cannot themselves be vouched for"
            return 1
        fi
        if [ "${owner}" != "0" ] &&
           [ "${owner}" != "${PLAYTHROUGH_UID}" ]; then
            export PLAYTHROUGH_UTILITY_TRUST="unresolved"
            playthrough_trust_unverifiable "'${path}' is owned by uid \
${owner}, which is neither root nor uid ${PLAYTHROUGH_UID}, so the \
program that performs every ownership check is itself somebody else's"
            return 1
        fi
        if [ $(( 8#${perm} & 8#022 )) -ne 0 ]; then
            export PLAYTHROUGH_UTILITY_TRUST="unresolved"
            playthrough_trust_unverifiable "'${path}' is mode ${perm}, \
i.e. group- or world-writable, so the program that performs every \
ownership check can be replaced between one call and the next"
            return 1
        fi
    done
    export PLAYTHROUGH_UTILITY_TRUST="trusted"
    return 0
}

# playthrough_assert_utilities [WHAT]
#   Refuse to PERFORM a security check whose tools are not trusted.
playthrough_assert_utilities() {
    local what="${1:-a security check}"
    if [ "${PLAYTHROUGH_UTILITY_TRUST:-unresolved}" = "trusted" ]; then
        return 0
    fi
    playthrough_die "${what} cannot be performed:" \
        "${PLAYTHROUGH_TRUST_UNVERIFIED:-the trusted utilities were" \
        "not resolved}.  This is a REFUSAL rather than a warning:" \
        "ownership and mode checks that did not run cannot report" \
        "success, because a caller has no way to tell that answer" \
        "from a verified one."
    return 1
}

_playthrough_bootstrap_utilities || true

# playthrough_validate_int VALUE LABEL [MIN] [MAX]
#   Accept a plain decimal integer and leave it in PLAYTHROUGH_INT, or
#   refuse it.
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
# ---------------------------------------------------------------------
# THE INHERITED ENVIRONMENT IS NOT TRUSTED EITHER
# Every external command in this tree is resolved by absolute path and verified
# -- owner, writability, and the same for every directory above it -- so that a
# tool another account can replace cannot decide a reading in the film.
# ---------------------------------------------------------------------
export PLAYTHROUGH_REFUSED_ENV_VARS="\
BASH_ENV ENV \
LD_PRELOAD LD_AUDIT LD_LIBRARY_PATH \
PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTHONUSERBASE PYTHONEXECUTABLE \
GIT_CONFIG GIT_CONFIG_COUNT GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE \
GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_NAMESPACE \
GIT_EXEC_PATH GIT_TEMPLATE_DIR GIT_SSH GIT_SSH_COMMAND \
GIT_EXTERNAL_DIFF GIT_PROXY_COMMAND GIT_ASKPASS \
MAGICK_HOME MAGICK_CONFIGURE_PATH MAGICK_CODER_MODULE_PATH \
MAGICK_FILTER_MODULE_PATH FONTCONFIG_FILE FFREPORT"

# playthrough_env_var_reason NAME
#   What NAME would let a caller do, in one sentence, so a refusal
#   explains itself instead of naming a variable and stopping.
playthrough_env_var_reason() {
    case "${1-}" in
        BASH_ENV|ENV)
            printf '%s' "bash SOURCES the file it names at the start of \
every non-interactive shell, so it runs inside all nine stages of this \
pipeline before their first line"
            ;;
        LD_PRELOAD|LD_AUDIT)
            printf '%s' "the shared object it names is loaded into \
every dynamically linked process this run starts -- the engine, \
ImageMagick, ffmpeg, tesseract and git among them -- and may override \
any symbol in them"
            ;;
        LD_LIBRARY_PATH)
            printf '%s' "it decides which shared libraries the verified \
binaries load, which is the same substitution their verification exists \
to prevent; a host that genuinely needs a library path should record it \
in /etc/ld.so.conf.d"
            ;;
        PYTHONPATH|PYTHONHOME)
            printf '%s' "it decides which modules this pipeline's own \
imports resolve to"
            ;;
        PYTHONSTARTUP|PYTHONEXECUTABLE)
            printf '%s' "it reaches the interpreter that reads every \
clock and composes every transition"
            ;;
        PYTHONUSERBASE)
            printf '%s' "it relocates the per-user site directory the \
interpreter imports from"
            ;;
        GIT_CONFIG|GIT_CONFIG_COUNT)
            printf '%s' "it injects arbitrary git configuration -- \
core.hooksPath, core.fsmonitor, a credential helper -- into every git \
call, outranking the containment this pipeline applies itself"
            ;;
        GIT_DIR|GIT_WORK_TREE|GIT_INDEX_FILE|GIT_OBJECT_DIRECTORY|\
GIT_ALTERNATE_OBJECT_DIRECTORIES|GIT_NAMESPACE)
            printf '%s' "it redirects where git reads the evidence from \
and writes it to, so a checkpoint could commit into another repository \
and report success"
            ;;
        GIT_EXEC_PATH|GIT_TEMPLATE_DIR|GIT_SSH|GIT_SSH_COMMAND|\
GIT_EXTERNAL_DIFF|GIT_PROXY_COMMAND|GIT_ASKPASS)
            printf '%s' "it names a program git executes, or a \
directory git executes its own subcommands from"
            ;;
        MAGICK_HOME|MAGICK_CONFIGURE_PATH|MAGICK_CODER_MODULE_PATH|\
MAGICK_FILTER_MODULE_PATH)
            printf '%s' "it names the module path ImageMagick loads its \
coders and filters from, which is code that runs on every frame this \
pipeline captures and crops"
            ;;
        FONTCONFIG_FILE)
            printf '%s' "it redirects font resolution, which is what \
the attested Terminus digest exists to pin"
            ;;
        FFREPORT)
            printf '%s' "it makes ffmpeg write a report to a \
caller-chosen path on every invocation"
            ;;
        *)
            printf '%s' "it is not part of this pipeline's environment \
contract"
            ;;
    esac
}

# playthrough_sanitize_environment
#   Refuse an inherited environment that could choose what code this run
#   executes, and verify the isolation levers that are allowed to remain.
playthrough_sanitize_environment() {
    local name value
    local -a offenders=()
    local -a names=()
    read -r -a names <<<"${PLAYTHROUGH_REFUSED_ENV_VARS}"
    for name in "${names[@]}"; do
        value="${!name-}"
        [ -n "${value}" ] || continue
        offenders+=("${name}=${value} -- $(
            playthrough_env_var_reason "${name}")")
    done
    # GIT_CONFIG_KEY_n / GIT_CONFIG_VALUE_n only take effect through
    # GIT_CONFIG_COUNT, which is refused above; they are named here too
    # so that a partial injection is reported rather than left in place
    # for the next run to complete.
    for name in $(compgen -A variable GIT_CONFIG_KEY_ 2>/dev/null) \
            $(compgen -A variable GIT_CONFIG_VALUE_ 2>/dev/null); do
        offenders+=("${name}=${!name} -- $(
            playthrough_env_var_reason GIT_CONFIG_COUNT)")
    done
    if [ "${#offenders[@]}" -gt 0 ]; then
        for name in "${offenders[@]}"; do
            playthrough_warn "refused environment: ${name}"
        done
        playthrough_die "this pipeline will not run with the" \
            "environment above.  Each of those variables lets whoever" \
            "set it choose what code the verified binaries execute, so" \
            "honouring one would run a caller's code and discarding" \
            "one silently would do something other than what the" \
            "caller asked.  There is no waiver: nothing about any host" \
            "requires them, and the fix is 'env -u <NAME> <command>'." \
            "Note that GIT_AUTHOR_*, GIT_COMMITTER_*," \
            "GIT_CONFIG_GLOBAL, GIT_CONFIG_SYSTEM and" \
            "GIT_CONFIG_NOSYSTEM are deliberately NOT in that list."
        return 1
    fi
    # The isolation levers, verified rather than refused.  A nominated
    # configuration file that another account can write is an injection
    # point wearing the clothes of a containment measure.
    for name in GIT_CONFIG_GLOBAL GIT_CONFIG_SYSTEM; do
        value="${!name-}"
        [ -n "${value}" ] || continue
        case "${value}" in
            /dev/null) continue ;;
        esac
        if [ ! -f "${value}" ]; then
            playthrough_die "${name}='${value}' does not name a" \
                "regular file.  It is git's own way to narrow which" \
                "configuration is read, so it is honoured -- but only" \
                "when what it names can be checked."
            return 1
        fi
        if playthrough_is_group_or_world_writable "${value}"; then
            playthrough_die "${name}='${value}' is writable by group" \
                "or other, so anybody on this host can put" \
                "core.hooksPath or a credential helper into every git" \
                "call this run makes.  Tighten it to 0600 or 0644."
            return 1
        fi
    done
    return 0
}

# playthrough_permission_bits PATH
#   Print PATH's three permission digits -- 644, 700, 666 -- with the
#   special-bits digit dropped, or fail with no output.
playthrough_permission_bits() {
    local path="${1-}"
    local raw
    [ -n "${path}" ] || return 1
    playthrough_assert_utilities \
        "reading the mode of '${path}'" || return 1
    raw="$("${PLAYTHROUGH_UTIL_STAT}" -Lc '%a' -- "${path}" \
        2>/dev/null || true)"
    [ -n "${raw}" ] || return 1
    if [ "${#raw}" -gt 3 ]; then
        raw="${raw#"${raw%???}"}"
    fi
    printf '%s' "${raw}"
}

# playthrough_is_group_or_world_writable PATH
#   True when PATH grants write access to group or other.  A PREDICATE,
#   silent on both answers, and FALSE when the mode cannot be read --
playthrough_is_group_or_world_writable() {
    local bits
    bits="$(playthrough_permission_bits "${1-}")" || return 1
    [ $(( 8#${bits} & 8#022 )) -ne 0 ]
}

# playthrough_untrusted_ancestor PATH
#   Print the first directory AT OR ABOVE PATH that is group- or
#   world-writable WITHOUT the sticky bit, walking all the way to '/'.
playthrough_untrusted_ancestor() {
    local path="${1-}"
    local entry bits
    [ -n "${path}" ] || return 1
    playthrough_assert_utilities \
        "measuring the ancestry of '${path}'" || return 1
    entry="$(playthrough_canonical_path "${path}")" || return 1
    while : ; do
        bits="$("${PLAYTHROUGH_UTIL_STAT}" -Lc '%a' -- "${entry}" \
            2>/dev/null || true)"
        if [ -n "${bits}" ] &&
           [ $(( 8#${bits} & 8#022 )) -ne 0 ] &&
           [ $(( 8#${bits} & 8#1000 )) -eq 0 ]; then
            printf '%s' "${entry}"
            return 0
        fi
        [ "${entry}" = "/" ] && break
        entry="${entry%/*}"
        [ -n "${entry}" ] || entry="/"
    done
    return 1
}

playthrough_secure_dir() {
    local path="${1-}"
    local mode="${2:-700}"
    local label="${3:-${1-}}"
    local owner uid kind actual
    if [ -z "${path}" ]; then
        playthrough_die "playthrough_secure_dir needs a path"
        return 1
    fi
    playthrough_assert_utilities \
        "verifying the private directory '${path}'" || return 1
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
    # Re-tested after the creation: a race that swapped the name between
    # the check above and the mkdir is caught here.
    kind="$("${PLAYTHROUGH_UTIL_STAT}" -Lc '%F' -- "${path}" \
        2>/dev/null || true)"
    if [ -L "${path}" ] || [ "${kind}" != "directory" ]; then
        playthrough_die "${label} '${path}' is a" \
            "${kind:-unreadable path}, not a real directory"
        return 1
    fi
    uid="${PLAYTHROUGH_UID:-$(_playthrough_euid)}"
    owner="$("${PLAYTHROUGH_UTIL_STAT}" -Lc '%u' -- "${path}" \
        2>/dev/null || true)"
    if [ "${owner}" != "${uid}" ]; then
        playthrough_die "${label} '${path}' is owned by uid" \
            "'${owner:-unknown}', not by uid ${uid}; refusing to" \
            "write the pipeline's runtime state into a directory" \
            "this user does not own"
        return 1
    fi
    # The mode BEFORE the chmod, so that a repair can be announced.
    local previous
    previous="$("${PLAYTHROUGH_UTIL_STAT}" -Lc '%a' -- "${path}" \
        2>/dev/null || true)"
    if ! "${PLAYTHROUGH_UTIL_CHMOD}" "${mode}" -- "${path}"; then
        playthrough_die "cannot chmod ${mode} ${label} '${path}'"
        return 1
    fi
    actual="$("${PLAYTHROUGH_UTIL_STAT}" -Lc '%a' -- "${path}" \
        2>/dev/null || true)"
    # THE PERMISSION BITS ARE THE CHECK, and the leading special-bits
    # digit is not part of it: a directory created inside a set-group-ID
    # parent inherits setgid, and GNU chmod preserves that bit when given
    # a three-digit octal mode, so `chmod 700` can leave `stat %a`
    # reading 2700 for ever.  2700 is as private as 700.  session.py's
    # _secure_dir() tests `st_mode & 0o077`, and the two must not drift.
    local actual_bits="${actual}"
    if [ "${#actual}" -gt 3 ]; then
        actual_bits="${actual#"${actual%???}"}"
    fi
    if [ "${actual_bits}" != "${mode}" ]; then
        playthrough_die "${label} '${path}' is mode" \
            "'${actual:-unknown}' after chmod ${mode}, i.e." \
            "permission bits '${actual_bits:-unknown}' rather than" \
            "${mode}"
        return 1
    fi
    local previous_bits="${previous}"
    if [ "${#previous}" -gt 3 ]; then
        previous_bits="${previous#"${previous%???}"}"
    fi
    if [ -n "${previous_bits}" ] && [ "${previous_bits}" != "${mode}" ]
    then
        playthrough_warn "${label} '${path}' was mode" \
            "${previous}, not ${mode}; it has been repaired to" \
            "${mode}, but something outside this pipeline widened it," \
            "and anything written there while it was open was" \
            "readable by other accounts on this host"
    fi
    return 0
}

# playthrough_secure_file PATH [MODE_OR_LABEL]
#   Ensure PATH is a regular file this user owns, creating it empty and private
#   if it is absent.  Existing content is preserved -- this is the append-safe
#   form; playthrough_secure_truncate is the other one.
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
    # The parent is derived with bash's own parameter expansion rather than by
    # calling `dirname`: this value is handed straight to
    # playthrough_secure_dir, so a substituted `dirname` on the inherited PATH
    # could point the mode-0700 adoption at a directory of its own choosing.
    case "${path}" in
        */*) dir="${path%/*}"; [ -n "${dir}" ] || dir="/" ;;
        *) dir="." ;;
    esac
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
    kind="$("${PLAYTHROUGH_UTIL_STAT}" -Lc '%F' -- "${path}" \
        2>/dev/null || true)"
    case "${kind}" in
        "regular file"|"regular empty file") ;;
        *)
            playthrough_die "${label} '${path}' is a" \
                "${kind:-unreadable path}, not a regular file"
            return 1
            ;;
    esac
    uid="${PLAYTHROUGH_UID:-$(_playthrough_euid)}"
    owner="$("${PLAYTHROUGH_UTIL_STAT}" -Lc '%u' -- "${path}" \
        2>/dev/null || true)"
    if [ "${owner}" != "${uid}" ]; then
        playthrough_die "${label} '${path}' is owned by uid" \
            "'${owner:-unknown}', not by uid ${uid}"
        return 1
    fi
    if ! "${PLAYTHROUGH_UTIL_CHMOD}" "${mode}" -- "${path}"; then
        playthrough_die "cannot chmod ${mode} ${label} '${path}'"
        return 1
    fi
    return 0
}

# playthrough_secure_truncate PATH [MODE_OR_LABEL]
#   playthrough_secure_file, then empty the file.  Used for logs and pid files
#   that a new run starts afresh; every other caller wants the append-safe form
#   above.
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
playthrough_verify_executable() {
    local path="${1-}"
    local label="${2:-executable}"
    if [ -z "${path}" ]; then
        playthrough_warn "no path given for ${label}"
        return 1
    fi
    # THE CHECK'S OWN TOOLS FIRST: `stat` and `readlink` are what this
    # verification is made of, so an unverifiable toolchain is a refusal
    # here rather than a check that quietly did nothing.
    playthrough_assert_utilities \
        "verifying ${label} '${path}'" || return 1
    local real
    real="$("${PLAYTHROUGH_UTIL_READLINK}" -f -- "${path}" \
        2>/dev/null || true)"
    if [ -z "${real}" ] || [ ! -f "${real}" ] || [ ! -x "${real}" ]; then
        playthrough_warn "${label} '${path}' is not an executable" \
            "regular file"
        return 1
    fi
    local entry="${real}"
    local perm owner
    while : ; do
        perm="$("${PLAYTHROUGH_UTIL_STAT}" -c '%a' -- "${entry}" \
            2>/dev/null || true)"
        owner="$("${PLAYTHROUGH_UTIL_STAT}" -c '%u' -- "${entry}" \
            2>/dev/null || true)"
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
#   Refuse a path that does not resolve inside ROOT.  readlink -m resolves
#   every existing component, so neither a `..` segment nor a symlink can
#   smuggle a destination past this.
playthrough_assert_inside() {
    local path="${1-}"
    local root="${2-}"
    local label="${3:-path}"
    local real_path real_root
    playthrough_assert_utilities \
        "resolving ${label} '${path}'" || return 1
    real_path="$("${PLAYTHROUGH_UTIL_READLINK}" -m -- "${path}" \
        2>/dev/null || true)"
    real_root="$("${PLAYTHROUGH_UTIL_READLINK}" -m -- "${root}" \
        2>/dev/null || true)"
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

# playthrough_verify_authority_file PATH
#   Prove that an X authority file is one this pipeline may read a
#   credential out of, or write one into.
playthrough_verify_authority_file() {
    local path="${1-}"
    local label="${2:-the X authority file}"
    local real kind owner perm entry
    if [ -z "${path}" ]; then
        playthrough_warn "no path given for ${label}"
        return 1
    fi
    playthrough_assert_utilities \
        "verifying ${label} '${path}'" || return 1
    if [ -L "${path}" ]; then
        playthrough_warn "${label} '${path}' is a symbolic link;" \
            "xauth writes THROUGH a link, so this is a write into" \
            "whatever it points at rather than an authority file"
        return 1
    fi
    real="$(playthrough_canonical_path "${path}")" || {
        playthrough_warn "${label} '${path}' cannot be resolved"
        return 1
    }
    if [ "${real}" != "${path}" ]; then
        playthrough_warn "${label} '${path}' reaches" \
            "'${real}' through a symlinked component; an authority" \
            "file is accepted only at its own canonical path, because" \
            "a link anywhere above it can be re-pointed between this" \
            "check and the next connection"
        return 1
    fi
    kind="$("${PLAYTHROUGH_UTIL_STAT}" -Lc '%F' -- "${real}" \
        2>/dev/null || true)"
    case "${kind}" in
        "regular file"|"regular empty file") ;;
        *)
            playthrough_warn "${label} '${path}' is a" \
                "${kind:-unreadable path}, not a regular file"
            return 1
            ;;
    esac
    owner="$("${PLAYTHROUGH_UTIL_STAT}" -Lc '%u' -- "${real}" \
        2>/dev/null || true)"
    if [ "${owner}" != "${PLAYTHROUGH_UID}" ]; then
        playthrough_warn "${label} '${path}' is owned by uid" \
            "'${owner:-unknown}', not by uid ${PLAYTHROUGH_UID}." \
            "A cookie another account chose authenticates that" \
            "account to the display this pipeline captures."
        return 1
    fi
    perm="$("${PLAYTHROUGH_UTIL_STAT}" -Lc '%a' -- "${real}" \
        2>/dev/null || true)"
    if [ -z "${perm}" ]; then
        playthrough_warn "cannot stat ${label} '${path}'"
        return 1
    fi
    if [ $(( 8#${perm} & 8#077 )) -ne 0 ]; then
        playthrough_warn "${label} '${path}' is mode ${perm}, so it" \
            "grants group or world access to a credential; whoever" \
            "can read the cookie can read the screen being captured" \
            "and send keystrokes into the session"
        return 1
    fi
    # THE WALK STOPS AT THE VERIFIED RUNTIME ROOT for its REFUSAL and
    # goes past it for its REPORT: the runtime root is already proved
    # private, so an unsafe ancestor above it is context rather than a
    # reason to refuse.
    if [ -n "${PLAYTHROUGH_RUNTIME_UNTRUSTED_ANCESTOR-}" ]; then
        playthrough_warn "${label} '${path}' is a credential inside" \
            "the private runtime anchor, and that anchor is reached" \
            "through '${PLAYTHROUGH_RUNTIME_UNTRUSTED_ANCESTOR}'," \
            "which is group- or world-writable and not sticky.  The" \
            "file's own mode and owner are verified below and hold;" \
            "what cannot be verified is that the PATH to it will still" \
            "name this file at the next connection.  The trust state" \
            "carries this already"
    fi
    local boundary=""
    boundary="$(playthrough_canonical_path "${XDG_RUNTIME_DIR:-}" \
        2>/dev/null || true)"
    entry="${real%/*}"
    [ -n "${entry}" ] || entry="/"
    while : ; do
        perm="$("${PLAYTHROUGH_UTIL_STAT}" -Lc '%a' -- "${entry}" \
            2>/dev/null || true)"
        if [ -z "${perm}" ]; then
            playthrough_warn "cannot stat '${entry}' while verifying" \
                "${label} '${path}'"
            return 1
        fi
        # 8#1000 is the sticky bit: a 1777 /tmp cannot be used to
        # replace a file inside a directory it does not own, which is
        # why a private 0700 tree under it is still private.
        if [ $(( 8#${perm} & 8#022 )) -ne 0 ] &&
           [ $(( 8#${perm} & 8#1000 )) -eq 0 ]; then
            playthrough_warn "${label} '${path}': '${entry}' is mode" \
                "${perm} -- group- or world-writable and not sticky --" \
                "so the authority file can be replaced by another" \
                "account between this check and the next connection"
            return 1
        fi
        if [ -n "${boundary}" ] && [ "${entry}" = "${boundary}" ]; then
            break
        fi
        [ "${entry}" = "/" ] && break
        entry="${entry%/*}"
        [ -n "${entry}" ] || entry="/"
    done
    return 0
}

# playthrough_canonical_path PATH
#   Print PATH with every `..`, every `.` and every symlinked component
#   resolved, WITHOUT requiring it to exist.  Empty input and an unresolvable
#   path are refusals rather than empty output, so a caller cannot mistake
#   "nothing to say" for "the root of the filesystem".
playthrough_canonical_path() {
    local path="${1-}"
    local real
    if [ -z "${path}" ]; then
        return 1
    fi
    playthrough_assert_utilities \
        "resolving the path '${path}'" || return 1
    real="$("${PLAYTHROUGH_UTIL_READLINK}" -m -- "${path}" \
        2>/dev/null || true)"
    if [ -z "${real}" ] || [ "${real#/}" = "${real}" ]; then
        return 1
    fi
    printf '%s' "${real}"
}

# playthrough_path_within BASE PATH
#   True when PATH is BASE itself or lies beneath it, both canonicalised first.
#   A PREDICATE, silent on both answers: the callers that must refuse print
#   their own reason, which is always more specific than anything a shared
#   helper could say.
playthrough_path_within() {
    local base="${1-}"
    local path="${2-}"
    local real_base real_path
    real_base="$(playthrough_canonical_path "${base}")" || return 1
    real_path="$(playthrough_canonical_path "${path}")" || return 1
    case "${real_path}" in
        "${real_base}"|"${real_base}"/*) return 0 ;;
    esac
    return 1
}

# playthrough_assert_no_symlink PATH ROOT LABEL
#   Walk every component of PATH below ROOT and refuse any that is a symbolic
#   link.  Containment alone is not enough: a symlink that points back inside
#   the tree would pass it, and the invariant this pipeline needs is that
#   frames, the build directory and the userdir are real directories nobody has
#   redirected.
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
# ---------------------------------------------------------------------
# THE ENVIRONMENT IS SANITISED FIRST, before this file resolves a path, starts
# a child or reads a file.
if ! playthrough_sanitize_environment; then
    return 1 2>/dev/null || exit 1
fi

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
# Cataclysm-DDA checkout.
if [ ! -d "${_playthrough_repo_root}/data" ] ||
   [ ! -f "${_playthrough_repo_root}/src/path_info.cpp" ]; then
    playthrough_die "'${_playthrough_repo_root}' is not a" \
        "Cataclysm-DDA checkout (no data/ or src/path_info.cpp)"
    return 1 2>/dev/null || exit 1
fi

# ---------------------------------------------------------------------
# Display and runtime directory
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

# XDG_RUNTIME_DIR must exist at mode 0700 before it is exported: SDL, Mesa and
# dbus all refuse or warn on a world-readable runtime directory, and a missing
# one produces a confusing SDL init failure.
_playthrough_legacy_anchor="/tmp/xdg${_playthrough_suffix}"
_playthrough_runtime_dir=""
_playthrough_unsafe_ancestor=""
if [ -n "${PLAYTHROUGH_XDG_ANCHOR-}" ]; then
    # A NOMINATION IS FATAL WHEN IT FAILS: an anchor an operator named
    # explicitly is never silently fallen back from.
    if ! playthrough_secure_dir "${PLAYTHROUGH_XDG_ANCHOR}" 700 \
            "XDG_RUNTIME_DIR"; then
        playthrough_die "PLAYTHROUGH_XDG_ANCHOR" \
            "'${PLAYTHROUGH_XDG_ANCHOR}' cannot be used as the private" \
            "runtime anchor (the reason is above).  It is not fallen" \
            "back from: a nominated anchor that quietly became a" \
            "different directory would put this run's credential and" \
            "locks somewhere nobody asked for."
        return 1 2>/dev/null || exit 1
    fi
    _playthrough_runtime_dir="${PLAYTHROUGH_XDG_ANCHOR}"
else
    # THE AUTOMATIC CHOICE.  The legacy anchor wins whenever it is
    # trusted OR already present; the /run candidate is reached only when
    # the legacy road is unsafe AND there is no live state to orphan.
    if [ -d "${_playthrough_legacy_anchor}" ] ||
       ! playthrough_untrusted_ancestor \
            "${_playthrough_legacy_anchor}" >/dev/null ||
       [ ! -d /run ]; then
        _playthrough_runtime_dir="${_playthrough_legacy_anchor}"
    else
        _playthrough_runtime_dir=\
"/run/playthrough-$(_playthrough_euid)${_playthrough_suffix}"
    fi
    if ! playthrough_secure_dir "${_playthrough_runtime_dir}" 700 \
            "XDG_RUNTIME_DIR"; then
        return 1 2>/dev/null || exit 1
    fi
fi
if ! _playthrough_unsafe_ancestor="$(playthrough_untrusted_ancestor \
        "${_playthrough_runtime_dir}")"; then
    _playthrough_unsafe_ancestor=""
fi
export XDG_RUNTIME_DIR="${_playthrough_runtime_dir}"
# THE ANCESTRY IS EXPORTED AS A FACT, so every stage and the acceptance gate
# read the same answer instead of each re-deriving it.
export PLAYTHROUGH_RUNTIME_UNTRUSTED_ANCESTOR=\
"${_playthrough_unsafe_ancestor-}"
unset _playthrough_legacy_anchor _playthrough_unsafe_ancestor

# ---------------------------------------------------------------------
# The private runtime root: one place for everything this pipeline writes
# OUTSIDE the working tree
# ---------------------------------------------------------------------
_playthrough_scratch_dir="${PLAYTHROUGH_RUNTIME_DIR:-\
${XDG_RUNTIME_DIR}/playthrough}"
if ! _playthrough_scratch_dir="$(playthrough_canonical_path \
        "${_playthrough_scratch_dir}")"; then
    playthrough_die "PLAYTHROUGH_RUNTIME_DIR" \
        "'${PLAYTHROUGH_RUNTIME_DIR:-<unset>}' cannot be resolved to" \
        "an absolute path, so it cannot be verified"
    return 1 2>/dev/null || exit 1
fi
if playthrough_path_within "${_playthrough_repo_root}" \
        "${_playthrough_scratch_dir}" ||
   playthrough_path_within "${_playthrough_scratch_dir}" \
        "${_playthrough_repo_root}"; then
    playthrough_die "the pipeline runtime root" \
        "'${_playthrough_scratch_dir}' is inside the checkout at" \
        "'${_playthrough_repo_root}' (or contains it).  It holds the X" \
        "cookie, the pid and lock files and any withdrawn frame, and" \
        "the terminal '!/playthrough/**' negation in .gitignore would" \
        "make those committable -- a credential in a commit and" \
        "diagnostics in an evidence tree.  Unset" \
        "PLAYTHROUGH_RUNTIME_DIR to use" \
        "'${XDG_RUNTIME_DIR}/playthrough', or nominate a directory" \
        "beneath '${XDG_RUNTIME_DIR}' that is outside the repository."
    return 1 2>/dev/null || exit 1
fi
if ! playthrough_path_within "${XDG_RUNTIME_DIR}" \
        "${_playthrough_scratch_dir}"; then
    playthrough_die "the pipeline runtime root" \
        "'${_playthrough_scratch_dir}' is not beneath the verified XDG" \
        "runtime root '${XDG_RUNTIME_DIR}'.  Only that root has been" \
        "proved to be a real, owner-only 0700 directory owned by this" \
        "user, and a runtime tree under an unverified ancestor can be" \
        "redirected or read by another account between one command and" \
        "the next.  Unset PLAYTHROUGH_RUNTIME_DIR, or nominate a" \
        "directory beneath '${XDG_RUNTIME_DIR}'."
    return 1 2>/dev/null || exit 1
fi
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
# Two variables below take a value spelled "dummy" and only ONE of them ever
# may:
#
#   SDL_AUDIODRIVER=dummy    CORRECT and required.  A headless host has no
#                            audio device, and the game runs with
#                            SOUND_ENABLED=false, so the null audio backend
#                            is exactly right.  Without it SDL_mixer spends
#                            the session retrying a device that will never
#                            appear.
#   SDL_VIDEODRIVER=dummy    CATASTROPHIC, and BANNED everywhere in this
#                            tree including as any script's default.  The
#                            dummy video backend renders ZERO PIXELS.  The
#                            game still runs, every keystroke still lands,
#                            `import -window root` still writes a PNG,
#                            ffmpeg still encodes, and every acceptance
#                            count still matches -- the only symptom is that
#                            the finished movie shows nothing at all.  It is
#                            the one completely silent failure mode of this
#                            pipeline, and the closest thing to accidental
#                            fabrication it can suffer.
#
# SDL_VIDEODRIVER is therefore exported UNCONDITIONALLY, and deliberately NOT
# written as "${SDL_VIDEODRIVER:-x11}": that is a default, and a caller who
# already had dummy in their environment would silently win.  This file
# overwrites it and then asserts the result.
#
# A dummy-driver frame measures mean=0 std=0 in grayscale, and a uniform
# solid colour measures mean>0 std=0, which is why verify_artifacts.sh
# asserts mean > 0 AND std > 0 as the backstop.  This file is the primary
# defence.
# ---------------------------------------------------------------------
export SDL_VIDEODRIVER=x11
export SDL_AUDIODRIVER=dummy

# No GPU exists on a headless host, so force the software rasteriser
# (llvmpipe).  Without this, GL initialisation can fail outright or
# fall back inconsistently between launches.
export LIBGL_ALWAYS_SOFTWARE=1

# ---------------------------------------------------------------------
# PYTHONDONTWRITEBYTECODE=1 is load-bearing, not hygiene
# ---------------------------------------------------------------------
export PYTHONDONTWRITEBYTECODE=1

# Line-buffer Python's stdout/stderr so that a long capture session
# reports progress as it happens instead of at exit.
export PYTHONUNBUFFERED=1

# PYTHONNOUSERSITE=1 IS `-s` FOR EVERY INTERPRETER THIS RUN STARTS, and
# exporting it is why `-s` does not have to be remembered at fifteen call
# sites.
export PYTHONNOUSERSITE=1

# ---------------------------------------------------------------------
# Artifact layout -- one authoritative definition for every sibling
# ---------------------------------------------------------------------
export PLAYTHROUGH_REPO_ROOT="${_playthrough_repo_root}"

# playthrough_rel PATH
#   PATH spelled relative to the repository root.  THE ONLY FORM A
#   MACHINE SUMMARY OR A DIAGNOSTIC REPORTS.
playthrough_rel() {
    local path="${1-}"
    case "${path}" in
        "") printf '%s' "" ;;
        "${PLAYTHROUGH_REPO_ROOT}")
            printf '%s' "." ;;
        "${PLAYTHROUGH_REPO_ROOT}"/*)
            printf '%s' "${path#"${PLAYTHROUGH_REPO_ROOT}"/}" ;;
        /*)
            printf '%s' \
                "<outside the checkout>/$(basename -- "${path}")" ;;
        *) printf '%s' "${path}" ;;
    esac
}

export PLAYTHROUGH_DIR="${_playthrough_repo_root}/playthrough"
export PLAYTHROUGH_TOOLING_DIR="${PLAYTHROUGH_DIR}/tooling"
export PLAYTHROUGH_FRAMES_DIR="${PLAYTHROUGH_DIR}/frames"
export PLAYTHROUGH_BUILD_DIR="${PLAYTHROUGH_DIR}/build"
export PLAYTHROUGH_TRANSITIONS_DIR="${PLAYTHROUGH_BUILD_DIR}/transitions"
export PLAYTHROUGH_USERDIR="${PLAYTHROUGH_DIR}/userdir"

# Engine-managed subtrees of the userdir. src/path_info.cpp:144 `savedir_value
# = user_dir_value + "save/";`, :164 `config_dir_value = user_dir_value +
# "config/";`, :167 `options_value = config_dir_value + "options.json";`.
export PLAYTHROUGH_SAVE_DIR="${PLAYTHROUGH_USERDIR}/save"
export PLAYTHROUGH_CONFIG_DIR="${PLAYTHROUGH_USERDIR}/config"
export PLAYTHROUGH_OPTIONS_JSON="${PLAYTHROUGH_CONFIG_DIR}/options.json"
_playthrough_kbjson="${PLAYTHROUGH_CONFIG_DIR}/keybindings.json"
export PLAYTHROUGH_KEYBINDINGS_JSON="${_playthrough_kbjson}"

# Data and media artifacts.
export PLAYTHROUGH_MANIFEST="${PLAYTHROUGH_DIR}/manifest.jsonl"
export PLAYTHROUGH_TIMELINE="${PLAYTHROUGH_DIR}/timeline.json"

# The AMENDMENT LEDGER, and why a correction lives outside the record it
# corrects.
export PLAYTHROUGH_AMENDMENTS="${PLAYTHROUGH_DIR}/amendments.jsonl"

# The capture telemetry sidecar, and why it exists SEPARATELY from the manifest
# rather than as extra manifest columns.
export PLAYTHROUGH_OBSERVATIONS="${PLAYTHROUGH_BUILD_DIR}/\
observations.jsonl"
export PLAYTHROUGH_CONCAT_LIST="${PLAYTHROUGH_BUILD_DIR}/concat.txt"

# The per-frame DATE AUDIT. One JSON object per captured frame, recording the
# sidebar date line -- display::date_string() (src/display.cpp:193-205) --
# beside the clock that was read from the same frame.
export PLAYTHROUGH_DATE_AUDIT="${PLAYTHROUGH_BUILD_DIR}/frame_dates.jsonl"

# The CAPTURE ATTESTATION LEDGER. One append-only row per published frame,
# naming its sha256 and its byte length.
export PLAYTHROUGH_FRAME_DIGESTS="${PLAYTHROUGH_BUILD_DIR}/\
frame_digests.jsonl"

# WHAT THE OPERATOR SAW BETWEEN THE KEYS, and it is named here because the
# acceptance gate reads it.
export PLAYTHROUGH_ACKNOWLEDGMENTS="${PLAYTHROUGH_BUILD_DIR}/\
acknowledgments.jsonl"

# THE ONE ARTIFACT THAT VOUCHES FOR THE OTHERS FROM OUTSIDE THEMSELVES.
export PLAYTHROUGH_EVIDENCE_ANCHOR="${PLAYTHROUGH_BUILD_DIR}/\
evidence_anchor.jsonl"
export PLAYTHROUGH_MOVIE="${PLAYTHROUGH_DIR}/cata-play.mp4"
export PLAYTHROUGH_MOVIE_CC="${PLAYTHROUGH_DIR}/cata-play-cc.mp4"
export PLAYTHROUGH_TRANSCRIPT_MD="${PLAYTHROUGH_DIR}/transcript.md"
export PLAYTHROUGH_TRANSCRIPT_SRT="${PLAYTHROUGH_DIR}/transcript.srt"
export PLAYTHROUGH_DOSSIER="${PLAYTHROUGH_DIR}/dossier.md"
export PLAYTHROUGH_TECH_NOTES="${PLAYTHROUGH_DIR}/TECHNICAL_NOTES.md"
# The mandated final report: exactly three sections, in the order the plan
# fixes them -- A) Screen Recording and Animation, B) Character Creation, C)
# Playing the Game.
export PLAYTHROUGH_REPORT="${PLAYTHROUGH_DIR}/REPORT.md"
# The COMMITTED acceptance report, and the scratch file it is published FROM.
# Two paths for one document, and the split is the whole point.
export PLAYTHROUGH_ACCEPTANCE_REPORT="${PLAYTHROUGH_DIR}/\
acceptance-report.txt"
export PLAYTHROUGH_ACCEPTANCE_SCRATCH="${PLAYTHROUGH_RUNTIME_DIR}/\
acceptance-report.txt"
export PLAYTHROUGH_REQUIREMENTS="${PLAYTHROUGH_TOOLING_DIR}/requirements.txt"
# The install contract beside the declaration. requirements.txt says WHICH six
# libraries; the lock says which exact wheel of each, by sha256.
export PLAYTHROUGH_REQUIREMENTS_LOCK="\
${PLAYTHROUGH_TOOLING_DIR}/requirements.lock"

# One printf format for the capture filename, so the capturer, the manifest
# writer and the concat list agree byte for byte.
export PLAYTHROUGH_FRAME_FORMAT='frame_%05d.png'
export PLAYTHROUGH_TRANSITION_FORMAT='trans_%05d_%02d.png'

# The game, and the exact command-line forms it is launched with.
export PLAYTHROUGH_GAME_BIN="${_playthrough_repo_root}/cataclysm-tiles"
export PLAYTHROUGH_GAME_BIN_ARG="./cataclysm-tiles"
export PLAYTHROUGH_USERDIR_ARG="./playthrough/userdir/"

# Diagnostic logs, inside the private runtime root established above -- which
# is already suffixed per checkout, so parallel clones cannot overwrite each
# other's diagnostics and no name here needs a suffix of its own.
export PLAYTHROUGH_GAME_LOG="${PLAYTHROUGH_LOG_DIR}/cata-play.log"
export PLAYTHROUGH_XVFB_LOG="${PLAYTHROUGH_LOG_DIR}/xvfb.log"
export PLAYTHROUGH_WM_LOG="${PLAYTHROUGH_LOG_DIR}/openbox.log"

# Pid files for the two host processes this file can start.
export PLAYTHROUGH_XVFB_PIDFILE="${PLAYTHROUGH_RUN_DIR}/xvfb.pid"
export PLAYTHROUGH_WM_PIDFILE="${PLAYTHROUGH_RUN_DIR}/openbox.pid"

# The supervisor program names that own the headless surface durably when a
# supervisor is configured on this host.
export PLAYTHROUGH_SUPERVISOR_XVFB="playthrough-xvfb\
${_playthrough_suffix}"
export PLAYTHROUGH_SUPERVISOR_WM="playthrough-openbox\
${_playthrough_suffix}"

# The X authority file: a per-run 128-bit MIT-MAGIC-COOKIE-1 for the contracted
# display, kept 0600 inside the private runtime root.
export PLAYTHROUGH_XAUTHORITY="${PLAYTHROUGH_RUNTIME_DIR}/Xauthority"
export PLAYTHROUGH_XAUTHORITY_INHERITED_REJECTED=""
if [ -n "${XAUTHORITY:-}" ] &&
   [ "${XAUTHORITY}" != "${PLAYTHROUGH_XAUTHORITY}" ] &&
   [ -e "${XAUTHORITY}" ]; then
    if playthrough_verify_authority_file "${XAUTHORITY}" \
            "the inherited XAUTHORITY"; then
        export PLAYTHROUGH_XAUTHORITY_ORIGIN="inherited"
    else
        export PLAYTHROUGH_XAUTHORITY_INHERITED_REJECTED="${XAUTHORITY}"
        export PLAYTHROUGH_XAUTHORITY_ORIGIN="pipeline"
        export XAUTHORITY="${PLAYTHROUGH_XAUTHORITY}"
        playthrough_warn "the inherited XAUTHORITY" \
            "'${PLAYTHROUGH_XAUTHORITY_INHERITED_REJECTED}' did not" \
            "pass verification (the reason is above), so it is NOT" \
            "used: this run falls back to its own 0600 cookie at" \
            "'${PLAYTHROUGH_XAUTHORITY}'.  If the display was" \
            "provisioned with that file, fix its ownership or mode --" \
            "or unset XAUTHORITY and let this pipeline own the" \
            "display -- rather than pointing this pipeline at a" \
            "credential it cannot vouch for."
    fi
else
    export PLAYTHROUGH_XAUTHORITY_ORIGIN="pipeline"
    export XAUTHORITY="${PLAYTHROUGH_XAUTHORITY}"
fi

# ---------------------------------------------------------------------
# Display, window and grid geometry
# ---------------------------------------------------------------------
export PLAYTHROUGH_SCREEN_WIDTH=1920
export PLAYTHROUGH_SCREEN_HEIGHT=1080
export PLAYTHROUGH_SCREEN_DEPTH=24
export PLAYTHROUGH_SCREEN="1920x1080x24"
export PLAYTHROUGH_WINDOW_CLASS="cataclysm-tiles"

# Terminal grid and font cell, used to seed options.json and to compute the
# sidebar OCR crop rather than hard-coding a rectangle. 36 cells is the default
# sidebar width from data/json/ui/sidebar.json:7 (custom_sidebar.width).
export PLAYTHROUGH_TERMINAL_X=240
export PLAYTHROUGH_TERMINAL_Y=67
export PLAYTHROUGH_FONT_WIDTH=8
export PLAYTHROUGH_FONT_HEIGHT=16

# The sidebar width in cells that the engine's own DEFAULT layout carries,
# recorded here for reporting only.
export PLAYTHROUGH_SIDEBAR_CELLS=44
export PLAYTHROUGH_SIDEBAR_LAYOUT="legacy_labels_sidebar"

# THE TILESET IS REQUIRED, NOT PREFERRED, and which one is decided once,
# here, on the plan's own words: the run is configured to the MSXotto+
# pack, so a launch that cannot find it refuses rather than falling back
# to whatever artwork happens to be installed.
export PLAYTHROUGH_TILESET="MshockXottoplus"

# AND WHICH BYTES IT MUST BE, stated OUTSIDE the artwork itself: the
# provenance anchor beside this file is what a composed pack is checked
# against, because a pack that vouches for itself vouches for nothing.

# Every name the required pack is known by, so a lookup can match the
# id, the view label, or the directory the pack ships as.  This is a
# spelling aid for ONE tileset, not a list of acceptable alternatives.
export PLAYTHROUGH_TILESET_ALIASES="MshockXottoplus MSXotto+ MShockXotto+"

# THERE IS NO SECOND TILESET IN THIS PIPELINE, and there is deliberately no
# variable naming one.

# Seconds to let a frame settle after a keystroke before capturing.
# The game redraws asynchronously; capturing too early photographs the
# previous frame and silently shifts every clock reading by one step.
export PLAYTHROUGH_SETTLE_SECONDS="0.3"

# ---------------------------------------------------------------------
# The Python interpreter
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
# AND THEN CHECK WHICH PYTHON IT IS: the lock names cp312 wheels, so an
# interpreter of another ABI cannot install the closure this pipeline was
# reviewed with, and the version it resolved is published for the record.
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
# ---------------------------------------------------------------------

# ---------------------------------------------------------------------
# THE PYTHON DEPENDENCY CLOSURE -- ONE ASSERTION, TWO CONSUMERS
#
# An interpreter that runs is not a closure that is installed: the gate
# and the sequencer both need to know that all six declared libraries are
# present AT the declared versions, so the question is asked once, here,
# and both read the same answer.
# ---------------------------------------------------------------------
# A PLAIN ASSIGNMENT, NOT `readonly`, and that is this file's own
# convention rather than an oversight: env.sh is designed to be sourced
# repeatedly -- by each stage, and by a stage a stage calls -- and it must
# be SILENT every time.  A `readonly` here made the second source print
# "PLAYTHROUGH_CLOSURE_CHECKER: readonly variable" to stderr, which
# test_env.py caught: nothing else in this file is readonly, for exactly
# that reason.
#
# SC2016: this is a Python program, and every `$` and `%` in it belongs to
# Python.  Single quotes are what keep the shell out of it.
# shellcheck disable=SC2016
PLAYTHROUGH_CLOSURE_CHECKER='
import importlib
import importlib.metadata as md
import re
import sys

US, REQ, LOCK = sys.argv[1], sys.argv[2], sys.argv[3]
ABI = (3, 12)

# The distribution name declared in requirements.txt, mapped to the module name
# an import statement actually uses.
MODULES = [
    ("moviepy", "moviepy"),
    ("pillow", "PIL"),
    ("pytesseract", "pytesseract"),
    ("numpy", "numpy"),
    ("imageio", "imageio"),
    ("imageio-ffmpeg", "imageio_ffmpeg"),
]
PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s\\;#]+)")

# The EARLIEST Pillow release carrying a fix for any advisory the pinned
# 11.3.0 is exposed to.  Fourteen distinct CVE identifiers were established
# against 11.3.0 on 2026-08-12, across three releases: CVE-2026-25990 (PSD)
# fixed in 12.1.1; CVE-2026-40192 (FITS bomb), CVE-2026-42309 (ImagePath) and
# CVE-2026-42311 (PSD) fixed in 12.2.0; and CVE-2026-54059 (PCF),
# CVE-2026-54060 (FontFile.compile), CVE-2026-55379 (BDF), CVE-2026-55380
# (GD), CVE-2026-59197 (RankFilter), CVE-2026-59199 (paste/crop),
# CVE-2026-59200 (PDF), CVE-2026-59203 (EPS), CVE-2026-59204 (JPEG2000) and
# CVE-2026-59205 (ImageCms) fixed in 12.3.0.  requirements.txt names the
# Pillow surface that shuts each one out, per record; not one is reachable
# from this pipeline.  The value below is the EARLIEST of the three on
# purpose: it is the first release the render stack would have to admit
# before ANY of those fixes became installable, which is the one thing this
# check can measure.
PILLOW_FIRST_FIXED = "12.1.1"

# The bootstrap tools belonging to the interpreter. These are NOT in the lock
# and must not be: pip installs the lock, so it cannot be an entry in it.
BOOTSTRAP = ("pip", "setuptools", "wheel")

# The one executable startup file the closure is permitted to contain, by
# sha256 of its exact bytes.
STARTUP_ALLOWED = {
    "distutils-precedence.pth":
        "2638ce9e2500e572a5e0de7faed6661eb569d1b696fcba07b0dd223da5f5d2"
        "24",
}


def say(kind, name, observed, expected=""):
    fields = (kind, name, observed, expected)
    sys.stdout.write(US.join(f.replace("\n", " ") for f in fields))
    sys.stdout.write("\n")


def norm(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def pins(path):
    found = {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                match = PIN.match(line)
                if match:
                    found[norm(match.group(1))] = match.group(2)
    except OSError as err:
        return None, str(err)
    return found, ""


failures = 0


def verdict(ok, name, observed, expected):
    global failures
    if ok:
        say("PASS", name, observed)
    else:
        failures += 1
        say("FAIL", name, observed, expected)


# 1  THE ABI.
actual = (sys.implementation.name, sys.version_info[0],
          sys.version_info[1])
want = ("cpython", ABI[0], ABI[1])
verdict(
    actual == want,
    "the interpreter is the CPython %d.%d the lock was built for"
    % ABI,
    "%s %d.%d.%d at %s"
    % (sys.implementation.name, sys.version_info[0],
       sys.version_info[1], sys.version_info[2], sys.executable),
    "CPython %d.%d -- numpy and Pillow ship per-interpreter binary "
    "wheels, so an interpreter of any other version is not running "
    "what requirements.lock installed" % ABI,
)

# 2  THE DECLARATION AGAINST THE LOCK.
declared, declared_err = pins(REQ)
locked, locked_err = pins(LOCK)
if declared is None or locked is None:
    verdict(
        False,
        "the declaration and the lock pin the same versions",
        "could not be read: %s" % (declared_err or locked_err),
        "a readable requirements.txt and requirements.lock",
    )
    declared = declared or {}
    locked = locked or {}
else:
    disagree = []
    for dist, _module in MODULES:
        key = norm(dist)
        mine = declared.get(key)
        theirs = locked.get(key)
        if mine is None:
            disagree.append("%s is absent from requirements.txt" % dist)
        elif theirs is None:
            disagree.append("%s is absent from requirements.lock" % dist)
        elif mine != theirs:
            disagree.append(
                "%s is ==%s in the declaration and ==%s in the lock"
                % (dist, mine, theirs))
    verdict(
        not disagree,
        "the declaration and the lock pin the same versions",
        "; ".join(disagree) if disagree
        else "all %d agree: %s" % (
            len(MODULES),
            ", ".join("%s==%s" % (d, declared[norm(d)])
                      for d, _m in MODULES)),
        "every library declared in requirements.txt pinned to the same "
        "version in requirements.lock -- the lock is the install "
        "contract for the declaration, and a divergence means the "
        "environment is not the one that was reviewed",
    )

# 3  WHAT IS INSTALLED.
installed = {}
wrong = []
for dist, _module in MODULES:
    want_version = declared.get(norm(dist))
    try:
        have = md.version(dist)
    except md.PackageNotFoundError:
        have = None
    except Exception as err:
        have = None
        wrong.append("%s could not be read: %s" % (dist, err))
        continue
    installed[dist] = have
    if have is None:
        wrong.append("%s is not installed" % dist)
    elif want_version is None:
        wrong.append("%s is installed (%s) but declared nowhere"
                     % (dist, have))
    elif have != want_version:
        wrong.append("%s is %s, declared ==%s"
                     % (dist, have, want_version))
verdict(
    not wrong,
    "every declared library is installed at its declared version",
    "; ".join(wrong) if wrong else ", ".join(
        "%s==%s" % (d, installed[d]) for d, _m in MODULES),
    "the six exact versions requirements.txt pins -- a floating "
    "version would let a release change the rendered film while every "
    "other gate still passed",
)

# 4  WHAT IMPORTS.
unimportable = []
for dist, module in MODULES:
    try:
        importlib.import_module(module)
    except Exception as err:
        unimportable.append("%s (import %s): %s"
                            % (dist, module, err))
verdict(
    not unimportable,
    "every declared library imports",
    "; ".join(unimportable) if unimportable
    else "all %d import cleanly: %s" % (
        len(MODULES), ", ".join(m for _d, m in MODULES)),
    "an import of each -- distribution metadata survives a "
    "half-removed package, and an import is what the pipeline "
    "actually does",
)

# 5  pip check, IN SUBSTANCE.
broken = []
try:
    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name
except Exception as err:
    verdict(
        False,
        "every installed distribution has its own requirements met",
        "packaging is not importable, so the dependency graph cannot "
        "be walked: %s" % err,
        "packaging installed -- it is in the lock as a transitive "
        "dependency and is what makes this check possible without "
        "spawning pip",
    )
else:
    present = {}
    for dist in md.distributions():
        name = dist.metadata["Name"]
        if name:
            present[canonicalize_name(name)] = dist.version
    walked = 0
    for dist in md.distributions():
        owner = dist.metadata["Name"] or "<unnamed>"
        for raw in dist.requires or []:
            try:
                req = Requirement(raw)
            except Exception:
                continue
            # Extras-gated requirements are not installed unless the
            # extra was asked for, so an absent one is not a fault.
            if req.marker is not None and not req.marker.evaluate(
                    {"extra": ""}):
                continue
            walked += 1
            have = present.get(canonicalize_name(req.name))
            if have is None:
                broken.append("%s requires %s, which is not installed"
                              % (owner, req.name))
            elif req.specifier and not req.specifier.contains(
                    have, prereleases=True):
                broken.append("%s requires %s%s but %s is installed"
                              % (owner, req.name, req.specifier, have))
    verdict(
        not broken,
        "every installed distribution has its own requirements met",
        "; ".join(sorted(set(broken))) if broken
        else "%d requirement(s) across %d distribution(s) all satisfied"
        % (walked, len(present)),
        "a complete, self-consistent dependency graph -- this is pip "
        "check in substance, computed from installed metadata so it "
        "needs neither pip nor a network",
    )

# 6 THE PIN THAT IS FORCED, AND STOPS BEING FORCED WITHOUT NOTICE.
try:
    from packaging.requirements import Requirement as _Req
    from packaging.utils import canonicalize_name as _canon
    from packaging.version import Version as _Ver
except Exception as err:
    verdict(
        False,
        "the render stack still forces the Pillow pin it is held at",
        "packaging is not importable, so the bound moviepy declares "
        "cannot be read: %s" % err,
        "packaging installed -- the bound has to be READ, because a "
        "pin justified by a constraint stops being justified the "
        "moment the constraint moves",
    )
else:
    bound = None
    bound_err = ""
    try:
        for raw in md.requires("moviepy") or []:
            req = _Req(raw)
            if _canon(req.name) != "pillow":
                continue
            if req.marker is not None and not req.marker.evaluate(
                    {"extra": ""}):
                continue
            bound = req.specifier
            break
    except Exception as err:
        bound_err = str(err)
    have_pillow = installed.get("pillow")
    if bound is None:
        # FAIL-CLOSED.  An unreadable bound is not "no constraint"; it
        # is a justification that can no longer be checked, and the pin
        # is only defensible while it can be.
        verdict(
            False,
            "the render stack still forces the Pillow pin it is held at",
            "moviepy declares no readable Pillow requirement%s"
            % (": %s" % bound_err if bound_err else ""),
            "moviepy to declare the Pillow range it was tested "
            "against -- without it there is nothing forcing 11.3.0 and "
            "nothing justifying it either",
        )
    elif have_pillow and _Ver(have_pillow) >= _Ver(PILLOW_FIRST_FIXED):
        verdict(
            True,
            "the render stack still forces the Pillow pin it is held at",
            "pillow is %s, at or past the first fixed release %s, so "
            "the exposure the pin was accepted for is closed"
            % (have_pillow, PILLOW_FIRST_FIXED),
            "either a Pillow at or past %s, or a render stack whose "
            "own declared bound still forces an earlier one"
            % PILLOW_FIRST_FIXED,
        )
    elif bound.contains(PILLOW_FIRST_FIXED, prereleases=True):
        verdict(
            False,
            "the render stack still forces the Pillow pin it is held at",
            "moviepy now declares pillow%s, which ADMITS the first "
            "fixed release %s -- so the constraint that justified "
            "pinning %s no longer exists"
            % (bound, PILLOW_FIRST_FIXED, have_pillow or "11.3.0"),
            "move BOTH pins together in requirements.txt and "
            "requirements.lock -- moviepy to the release that lifted "
            "the cap and pillow to the newest it allows at or past "
            "%s -- then re-run the transition path end to end before "
            "trusting it with a render.  Do NOT raise the Pillow pin "
            "alone" % PILLOW_FIRST_FIXED,
        )
    else:
        verdict(
            True,
            "the render stack still forces the Pillow pin it is held at",
            "moviepy declares pillow%s, which excludes the first fixed "
            "release %s, so %s remains the newest permitted and the "
            "accepted risk is still forced rather than chosen"
            % (bound, PILLOW_FIRST_FIXED, have_pillow or "11.3.0"),
            "either a Pillow at or past %s, or a render stack whose "
            "own declared bound still forces an earlier one"
            % PILLOW_FIRST_FIXED,
        )

# 7  NOTHING IS INSTALLED THAT THE LOCK DOES NOT NAME.  Checks 2-5 ask
# whether what was declared is present and coherent; this one asks the
# opposite question, because an extra distribution nobody reviewed is
# just as much a change to the render stack as a missing one.
extra = []
if locked:
    allowed = set(locked)
    allowed.update(norm(name) for name in BOOTSTRAP)
    try:
        for dist in md.distributions():
            name = dist.metadata["Name"]
            if not name:
                extra.append("an unnamed distribution at %s"
                             % getattr(dist, "_path", "<unknown>"))
            elif norm(name) not in allowed:
                extra.append("%s==%s" % (name, dist.version))
    except Exception as err:
        extra.append("the installed set could not be enumerated: %s"
                     % err)
    verdict(
        not extra,
        "nothing is installed that requirements.lock does not name",
        "; ".join(sorted(set(extra))) if extra
        else "%d distribution(s), all named by the lock or one of the "
             "%d bootstrap tools (%s)"
             % (len(allowed), len(BOOTSTRAP), ", ".join(BOOTSTRAP)),
        "an environment containing the locked closure and the "
        "bootstrap tools of the interpreter and NOTHING else -- an "
        "undeclared distribution is one no hash pinned and no review "
        "saw, and every module in the closure can import it",
    )
else:
    verdict(
        False,
        "nothing is installed that requirements.lock does not name",
        "the lock could not be read, so the installed set has nothing "
        "to be compared against",
        "a readable requirements.lock",
    )

# 8 NOTHING RUNS AT INTERPRETER STARTUP THAT WAS NOT ALLOWED. A .pth file in
# site-packages whose line begins `import` is executed by the site module on
# EVERY interpreter start, before main() and before any check in this program.
startup = []
try:
    import os as _os
    import sysconfig as _sysconfig
    import hashlib as _hashlib

    roots = []
    for key in ("purelib", "platlib"):
        path = _sysconfig.get_paths().get(key)
        if path and path not in roots:
            roots.append(path)
    scanned = 0
    for root in roots:
        if not _os.path.isdir(root):
            continue
        for entry in sorted(_os.listdir(root)):
            if not entry.endswith(".pth"):
                continue
            scanned += 1
            full = _os.path.join(root, entry)
            try:
                with open(full, "rb") as handle:
                    body = handle.read()
            except OSError as err:
                startup.append("%s could not be read: %s" % (entry, err))
                continue
            executable = [
                line for line in body.decode(
                    "utf-8", "replace").splitlines()
                if line.strip().startswith(("import ", "import\t"))
            ]
            if not executable:
                continue
            digest = _hashlib.sha256(body).hexdigest()
            want = STARTUP_ALLOWED.get(entry)
            if want is None:
                startup.append(
                    "%s executes %d line(s) at startup and is not an "
                    "allowed startup file (sha256 %s)"
                    % (entry, len(executable), digest[:16]))
            elif digest != want:
                startup.append(
                    "%s is an allowed startup file but its bytes have "
                    "changed: sha256 %s, expected %s"
                    % (entry, digest[:16], want[:16]))
except Exception as err:
    startup.append("the startup files could not be inventoried: %s"
                   % err)
verdict(
    not startup,
    "nothing runs at interpreter startup that was not allowed",
    "; ".join(sorted(set(startup))) if startup
    else "%d .pth file(s) present; every executable one is allowed by "
         "digest (%s)"
         % (scanned if "scanned" in dir() else 0,
            ", ".join(sorted(STARTUP_ALLOWED)) or "none"),
    "every executable .pth allowed by the sha256 of its exact bytes -- "
    "a .pth beginning `import` runs before any pipeline code, so "
    "allowing one by NAME would allow any content under that name",
)

say("INFO", "the installed dependency closure",
    ", ".join("%s==%s" % (d, installed.get(d) or "ABSENT")
              for d, _m in MODULES))

sys.exit(1 if failures else 0)
'

# playthrough_write_closure_checker PATH
#   Materialise the shared closure checker at PATH.  Callers put it in their
#   own private scratch directory rather than in the working tree, because a
#   stage that added an untracked file to the evidence is a stage the
#   acceptance gate would, correctly, report.
playthrough_write_closure_checker() {
    local path="${1-}"
    if [ -z "${path}" ]; then
        playthrough_warn "no path given for the closure checker"
        return 1
    fi
    printf '%s\n' "${PLAYTHROUGH_CLOSURE_CHECKER}" >"${path}" || {
        playthrough_warn "cannot write the closure checker to" \
            "'${path}'"
        return 1
    }
    return 0
}

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
# Several checks in this pipeline can be relaxed for diagnosis: an interpreter
# or tool that cannot be verified, a display this pipeline did not start and
# cannot prove is authenticated, a tileset pack on a world-writable path,
# artwork other than the required MSXotto+, a Pillow older than the pin, a
# compiler the project does not sanction, and a host whose release no longer
# receives security fixes.
# ---------------------------------------------------------------------
export PLAYTHROUGH_TRUST_BYPASS_VARS="\
PLAYTHROUGH_ALLOW_UNVERIFIED_EXECUTABLES \
PLAYTHROUGH_ALLOW_UNAUTHENTICATED_X \
PLAYTHROUGH_ALLOW_UNVERIFIED_TILESET_PACK \
PLAYTHROUGH_ALLOW_VULNERABLE_PILLOW \
PLAYTHROUGH_ALLOW_ANY_COMPILER \
PLAYTHROUGH_ALLOW_UNSAFE_PATH_ANCESTRY \
PLAYTHROUGH_ALLOW_EOL_PLATFORM"

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
        PLAYTHROUGH_ALLOW_VULNERABLE_PILLOW)
            printf '%s' "frames are decoded by a Pillow older than \
the pinned, reviewed one"
            ;;
        PLAYTHROUGH_ALLOW_ANY_COMPILER)
            printf '%s' "the binary may have been built by a compiler \
the project does not sanction"
            ;;
        PLAYTHROUGH_ALLOW_UNSAFE_PATH_ANCESTRY)
            printf '%s' "a component of the path to this run's own \
evidence or runtime state can be renamed or replaced by another local \
account, so a frame, a save or a lock may not be the one this pipeline \
wrote"
            ;;
        PLAYTHROUGH_ALLOW_EOL_PLATFORM)
            printf '%s' "the ImageMagick, ffmpeg and Xorg/Xvfb \
packages that capture, decode and encode every frame receive no \
further security fixes on this release"
            ;;
        *)
            printf '%s' "an unrecognised trust override is set"
            ;;
    esac
}

# playthrough_trust_refresh
#   Recompute the trust state from the environment as it is NOW, export
#   it, and report it: 0 when trusted, 1 when any bypass is active.
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
    export PLAYTHROUGH_TRUST_UNVERIFIED="${PLAYTHROUGH_TRUST_UNVERIFIED-}"
    # THE SECOND INPUT, and it is not a bypass: a check that could not be
    # PERFORMED leaves the state diagnostic too, because "we could not
    # look" is not evidence that nothing was wrong.
    if [ -n "${active}" ] ||
       [ -n "${PLAYTHROUGH_TRUST_UNVERIFIED}" ]; then
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
    if [ -n "${PLAYTHROUGH_TRUST_UNVERIFIED-}" ]; then
        playthrough_warn "a security check could not be performed:" \
            "${PLAYTHROUGH_TRUST_UNVERIFIED}.  This is reported as a" \
            "trust state rather than only as a warning, because the" \
            "answer 'not checked' has to reach the stages that did not" \
            "make the call."
    fi
    return 1
}

# playthrough_assert_trusted [CONTEXT]
#   THE GATE.  Call it from anything that is about to produce evidence.
#   Returns 0 when no bypass is active; otherwise explains every active one and
#   refuses, returning 1 (this file is sourced, so it cannot exit -- the caller
#   turns the refusal into its own exit code).
playthrough_assert_trusted() {
    local context="${1:-an action that produces evidence}"
    if playthrough_trust_refresh; then
        return 0
    fi
    playthrough_trust_explain
    local why="${PLAYTHROUGH_TRUST_BYPASSES// /, }"
    if [ -n "${PLAYTHROUGH_TRUST_UNVERIFIED-}" ]; then
        why="${why}${why:+; }${PLAYTHROUGH_TRUST_UNVERIFIED}"
    fi
    playthrough_die "refusing ${context} while the trust state is" \
        "diagnostic (${why}).  Evidence" \
        "produced under a relaxed check is not evidence: unset the" \
        "variable(s) above and fix what each one was hiding, or keep" \
        "diagnosing with PLAYTHROUGH_CAPTURE_MODE=diagnostic, whose" \
        "frames are withdrawn out of the working tree and can never be" \
        "committed as part of the record."
    return 1
}

# ---------------------------------------------------------------------
# WHICH APT PACKAGE SHIPS WHICH COMMAND
# Named here so that a missing-tool diagnostic can say what to install rather
# than only what is absent.
# ---------------------------------------------------------------------
playthrough_tool_package() {
    case "$1" in
        Xvfb) printf '%s\n' "xvfb" ;;
        openbox) printf '%s\n' "openbox" ;;
        xdpyinfo|xwininfo|xprop) printf '%s\n' "x11-utils" ;;
        xdotool) printf '%s\n' "xdotool" ;;
        import|convert|identify|compare|mogrify|stream)
            printf '%s\n' "imagemagick" ;;
        ffmpeg|ffprobe) printf '%s\n' "ffmpeg" ;;
        tesseract) printf '%s\n' "tesseract-ocr" ;;
        scrot) printf '%s\n' "scrot" ;;
        make) printf '%s\n' "make" ;;
        ccache) printf '%s\n' "ccache" ;;
        setsid|nohup|kill|env|readlink|tr|head|tail|sleep|mkdir|chmod|\
sha256sum|stat|timeout|id|realpath|cut|cp|mv|rm|wc|dirname|basename|\
cat|ls|sort|touch|pwd|date|df|du|mktemp|od)
            printf '%s\n' "coreutils" ;;
        find|xargs) printf '%s\n' "findutils" ;;
        flock|mcookie) printf '%s\n' "util-linux" ;;
        git) printf '%s\n' "git" ;;
        xauth) printf '%s\n' "xauth" ;;
        grep) printf '%s\n' "grep" ;;
        awk) printf '%s\n' "mawk or gawk" ;;
        sed) printf '%s\n' "sed" ;;
        bash) printf '%s\n' "bash" ;;
        pkg-config) printf '%s\n' "pkg-config" ;;
        msgfmt) printf '%s\n' "gettext" ;;
        g++-14) printf '%s\n' "g++-14" ;;
        supervisorctl) printf '%s\n' "supervisor" ;;
        *) printf '%s\n' "unknown package" ;;
    esac
}

# playthrough_tool_var NAME
#   The variable a resolved tool is exported as: `convert` becomes
#   PLAYTHROUGH_BIN_CONVERT and `g++-14` becomes PLAYTHROUGH_BIN_G__14.
playthrough_tool_var() {
    printf 'PLAYTHROUGH_BIN_%s\n' \
        "$(printf '%s' "${1-}" |
            tr '[:lower:]' '[:upper:]' |
            tr -c '[:upper:][:digit:]' '_')"
}

# playthrough_resolve_tool NAME
#   Resolve NAME on PATH, verify it, and export PLAYTHROUGH_BIN_<NAME>
#   with the path that will actually be invoked.
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
#   Assert that external commands exist AND are trustworthy, reporting ALL that
#   fail rather than dying on the first, naming the package that ships each
#   missing one, and exporting a verified PLAYTHROUGH_BIN_<NAME> for each that
#   passes so callers invoke a checked path instead of re-searching PATH
#   themselves.
playthrough_require_tools() {
    local tools=("$@")
    local missing=()
    local rejected=()
    local tool
    if [ "${#tools[@]}" -eq 0 ]; then
        tools=(
            Xvfb openbox xdpyinfo xwininfo xprop xdotool xauth
            import convert identify ffmpeg ffprobe tesseract flock
            setsid nohup grep awk sed bash
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
        # ABSENT AND UNTRUSTWORTHY ARE DIFFERENT FAULTS and are reported as
        # such: one is answered by installing a package, the other by finding
        # out who owns a binary this pipeline is being asked to run.
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
#   Three-way answer about the contracted display -- 0 serving, 1 not
#   answering, 2 unable to ask -- because "no display" and "no xdpyinfo"
#   would otherwise wear the same face.
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
#   True when an X server is answering on the contracted display.  A missing
#   xdpyinfo is NOT ready, and the distinction is reported once so it cannot be
#   mistaken for a dead server on every poll.
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
#   Poll until the display answers. Default timeout 30 s.
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
    # THE SOCKET IS ASKED ABOUT BEFORE THE REFUSAL IS PRINTED, because
    # "nothing is answering" has two very different causes -- no server
    # was ever started, and a server died leaving its socket behind --
    # and the second one is the fault an operator cannot see.
    playthrough_diagnose_x_socket || true
    playthrough_die "no X server answering on" \
        "${PLAYTHROUGH_DISPLAY} after ${timeout}s (log:" \
        "${PLAYTHROUGH_XVFB_LOG})"
    return 1
}

# ---------------------------------------------------------------------
# PROCESS LIFECYCLE -- WHAT DETACHMENT DOES AND DOES NOT BUY
# Read this before relying on anything below to still be running.
# ---------------------------------------------------------------------

# playthrough_spawn_detached NAME PIDFILE LOGFILE -- CMD [ARG ...]
#   Start one long-lived child as detached as a shell can make it, and PROVE it
#   started.  Writes the child's pid to PIDFILE, returns 0 only when that pid
#   is still alive a moment later, and reports the log to look in when it is
#   not.
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
        {PLAYTHROUGH_CHILD_CLOSE_FD}>&- \
        {PLAYTHROUGH_CHILD_CLOSE_FD2}>&- &
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
    # A short settle, then proof of life.
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
#   True when a process supervisor is installed AND answering.  Being installed
#   is not enough: supervisord's socket refuses connections when the daemon
#   itself is not running, which is exactly the state a torn-down tree leaves
#   behind.
playthrough_supervisor_available() {
    command -v supervisorctl >/dev/null 2>&1 || return 1
    supervisorctl status >/dev/null 2>&1
}

# playthrough_supervisor_start PROGRAM
#   Ask the supervisor to run one program and report whether it is RUNNING
#   afterwards.  Returns 1 when there is no supervisor, when the program is not
#   configured, or when it did not come up -- in every one of those cases the
#   caller falls back to verified detachment, which is why this reports rather
#   than dies.
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
#   128 bits of hex for one MIT-MAGIC-COOKIE-1 entry.  mcookie is preferred
#   because it is purpose-built; /dev/urandom is the fallback so a host without
#   util-linux still gets a real random cookie rather than something guessable.
playthrough_xauth_cookie() {
    if command -v mcookie >/dev/null 2>&1 &&
       playthrough_require_tools mcookie >/dev/null 2>&1; then
        "${PLAYTHROUGH_BIN_MCOOKIE}"
        return 0
    fi
    playthrough_require_tools od tr >/dev/null 2>&1 || {
        playthrough_die "neither mcookie nor a verified od and tr are" \
            "available, so a 128-bit X cookie cannot be generated." \
            "Install util-linux (mcookie) or coreutils (od, tr)."
        return 1
    }
    "${PLAYTHROUGH_BIN_OD}" -An -tx1 -N16 /dev/urandom |
        "${PLAYTHROUGH_BIN_TR}" -d ' \n'
    printf '\n'
}

# playthrough_xauth_digest
#   A sha256 of the MIT-MAGIC-COOKIE-1 entry the active authority file
#   holds for the contracted display, or nothing.
playthrough_xauth_digest() {
    local file="${XAUTHORITY:-${PLAYTHROUGH_XAUTHORITY}}"
    local entry="" value=""
    [ -f "${file}" ] || return 1
    command -v xauth >/dev/null 2>&1 || return 1
    command -v sha256sum >/dev/null 2>&1 || return 1
    entry="$(xauth -f "${file}" list "${PLAYTHROUGH_DISPLAY}" \
        2>/dev/null | grep 'MIT-MAGIC-COOKIE-1' | head -n 1 || true)"
    [ -n "${entry}" ] || return 1
    # The hex value is the last field; the display name before it differs
    # between hosts (it carries the hostname), so hashing the whole line
    # would report a difference where the cookie had not changed.
    value="${entry##* }"
    case "${value}" in
        ''|*[!0-9a-fA-F]*) return 1 ;;
    esac
    printf '%s' "$(printf '%s' "${value}" | sha256sum | cut -c1-16)"
    return 0
}

# playthrough_ensure_xauth
#   Make sure the active XAUTHORITY file holds a cookie for this
#   display, generating one if it does not.
playthrough_ensure_xauth() {
    playthrough_require_tools xauth || return 1
    local mode="${1-}"
    local file="${XAUTHORITY:-${PLAYTHROUGH_XAUTHORITY}}"
    if [ "${PLAYTHROUGH_XAUTHORITY_ORIGIN}" = "pipeline" ]; then
        playthrough_secure_file "${file}" 600 || return 1
    elif ! playthrough_verify_authority_file "${file}" \
            "the inherited XAUTHORITY"; then
        playthrough_die "the inherited XAUTHORITY '${file}' cannot be" \
            "used (the reason is above).  Unset XAUTHORITY to let this" \
            "pipeline own a verified 0600 cookie at" \
            "'${PLAYTHROUGH_XAUTHORITY}', or fix the file's path," \
            "owner and mode."
        return 1
    fi
    local present="no"
    if xauth -f "${file}" list "${PLAYTHROUGH_DISPLAY}" 2>/dev/null |
            grep -q 'MIT-MAGIC-COOKIE-1'; then
        present="yes"
    fi
    if [ "${present}" = "yes" ] && [ "${mode}" != "fresh" ]; then
        return 0
    fi
    if [ "${present}" = "yes" ] && [ "${mode}" = "fresh" ]; then
        # ROTATION IS ONLY EVER DONE TO AN AUTHORITY FILE THIS PIPELINE OWNS.
        if [ "${PLAYTHROUGH_XAUTHORITY_ORIGIN}" != "pipeline" ]; then
            playthrough_log "reusing the inherited authority file's" \
                "existing cookie for ${PLAYTHROUGH_DISPLAY}: rotating" \
                "an entry this pipeline did not create would break" \
                "clients it cannot see.  The cookie's digest is bound" \
                "into the ownership record either way, so a later" \
                "rotation by its owner is detected rather than assumed"
            return 0
        fi
        if ! xauth -f "${file}" -q remove "${PLAYTHROUGH_DISPLAY}"; then
            playthrough_die "could not remove the previous cookie for" \
                "${PLAYTHROUGH_DISPLAY} from '${file}', so a fresh one" \
                "cannot be guaranteed to be the only one.  A server" \
                "started with an unaccounted cookie is not started."
            return 1
        fi
        playthrough_log "removed the previous MIT-MAGIC-COOKIE-1 for" \
            "${PLAYTHROUGH_DISPLAY} from ${file}: a new server" \
            "generation gets a cookie this run chose, not one it" \
            "inherited from a server that is gone"
    fi
    if [ "${PLAYTHROUGH_XAUTHORITY_ORIGIN}" != "pipeline" ] &&
       [ "${PLAYTHROUGH_ALLOW_INHERITED_XAUTH_WRITE:-0}" != "1" ]; then
        playthrough_die "the inherited XAUTHORITY '${file}' carries no" \
            "MIT-MAGIC-COOKIE-1 for ${PLAYTHROUGH_DISPLAY}, and this" \
            "pipeline does not write into an authority file it did not" \
            "create.  Three ways forward, in the order they should be" \
            "preferred: provision the cookie for" \
            "${PLAYTHROUGH_DISPLAY} in that file yourself; unset" \
            "XAUTHORITY so this pipeline owns a verified 0600 cookie" \
            "at '${PLAYTHROUGH_XAUTHORITY}'; or set" \
            "PLAYTHROUGH_ALLOW_INHERITED_XAUTH_WRITE=1 to authorise" \
            "one xauth add into that verified file."
        return 1
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
# PROCESS LIFETIME -- WHAT setsid DOES AND WHAT IT DOES NOT DO
#
# Read this before relying on anything below to still be running: the
# distinction is the difference between a session that completes and one
# that vanishes half-captured.
# ---------------------------------------------------------------------

# The provisioned durable X surface, if the host has one.
export PLAYTHROUGH_SUPERVISED_X_CONF="\
/etc/supervisor/conf.d/playthrough-x.conf"
export PLAYTHROUGH_SUPERVISED_X_UNITS="\
playthrough-xvfb playthrough-openbox"
export PLAYTHROUGH_SUPERVISED_DISPLAY_NUM=99

# playthrough_supervised_x_serves_display
#   True when the provisioned durable service exists, is drivable, and
#   serves THIS run's contracted display.
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
playthrough_start_supervised_x() {
    playthrough_supervised_x_serves_display || return 1
    # supervisorctl needs the daemon; on a freshly started host the socket may
    # not be answering yet even though the unit files are installed.
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
        # This checkout asked for the unit and can restart it, so the
        # ownership is real even though the process is not in this
        # shell's tree -- and it is recorded as 'supervisor' rather than
        # 'pipeline' so a reader can tell the two apart.
        playthrough_record_x_ownership supervisor "" || return 1
        return 0
    fi
    return 1
}

# playthrough_start_xvfb
#   Bring up the headless X server ONLY if the display is not already
#   answering, so an externally managed server -- the provisioned durable
#   service, a container sidecar -- is left strictly alone.
playthrough_start_xvfb() {
    if playthrough_display_ready; then
        return 0
    fi
    # THE DURABLE SURFACE FIRST, in the order the operator asked for.
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
    # `fresh`: this is the one call site that is about to CREATE a server,
    # so it is the one that may rotate the cookie.  See
    # playthrough_ensure_xauth for why no other caller does.
    playthrough_ensure_xauth fresh || return 1
    mkdir -p /tmp/.X11-unix 2>/dev/null || true
    playthrough_secure_truncate "${PLAYTHROUGH_XVFB_LOG}" || return 1
    playthrough_log "starting Xvfb on ${PLAYTHROUGH_DISPLAY} at" \
        "${PLAYTHROUGH_SCREEN}, authenticated with" \
        "${XAUTHORITY:-${PLAYTHROUGH_XAUTHORITY}}; its lifetime is" \
        "this shell's process tree"
    # -auth is as load-bearing as -nolisten tcp: one closes the network socket,
    # the other the local one.
    playthrough_spawn_detached "Xvfb ${PLAYTHROUGH_DISPLAY}" \
        "${PLAYTHROUGH_XVFB_PIDFILE}" "${PLAYTHROUGH_XVFB_LOG}" -- \
        Xvfb "${PLAYTHROUGH_DISPLAY}" \
        -screen 0 "${PLAYTHROUGH_SCREEN}" -nolisten tcp \
        -auth "${XAUTHORITY:-${PLAYTHROUGH_XAUTHORITY}}" || return 1
    playthrough_wait_for_display 30 || return 1
    # OWNERSHIP IS RECORDED AT THE ONE MOMENT IT IS KNOWN.  After this
    # returns, "who started the server" is not derivable from anything
    # on the host: Xvfb has no notion of the checkout that spawned it.
    playthrough_record_x_ownership pipeline \
        "$(cat "${PLAYTHROUGH_XVFB_PIDFILE}" 2>/dev/null || true)" ||
        return 1
    return 0
}

# ---------------------------------------------------------------------
# WHO OWNS THE DISPLAY -- AN ANSWER, NOT AN ASSUMPTION
#
# "A server is answering on :99" and "this checkout brought that server
# up" are different facts, and only the second one licenses a capture.
# ---------------------------------------------------------------------

# playthrough_x_ownership_record
#   The path of the ownership record for the contracted display.
playthrough_x_ownership_record() {
    printf '%s' "${PLAYTHROUGH_RUN_DIR}/x-ownership${PLAYTHROUGH_DISPLAY_NUM}"
}

# playthrough_signal_pid KIND PID [SIGNAL]
#   Signal a process THROUGH A HANDLE, never through its number.
playthrough_signal_pid() {
    local kind="${1-}" pid="${2-}" signal="${3:-SIGTERM}"
    case "${pid}" in
        ''|*[!0-9]*) return 1 ;;
    esac
    # The program is handed a fixed script and four arguments; nothing is
    # interpolated into it.  It prints one line to stderr when it refuses
    # so the caller can quote the reason.
    "${PLAYTHROUGH_PYTHON}" -c '
import os
import signal
import sys

kind, text, name = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    pid = int(text)
except ValueError:
    sys.stderr.write("%s is not a pid\n" % text)
    raise SystemExit(1)
opener = getattr(os, "pidfd_open", None)
sender = getattr(signal, "pidfd_send_signal", None)
if opener is None or sender is None:
    sys.stderr.write(
        "this interpreter has no pidfd support, so the process cannot "
        "be signalled through a handle\n")
    raise SystemExit(2)
try:
    handle = opener(pid)
except (OSError, AttributeError) as err:
    if getattr(err, "errno", None) == 38:   # ENOSYS: no pidfd_open
        sys.stderr.write(
            "this kernel has no pidfd_open, so the process cannot be "
            "signalled through a handle\n")
        raise SystemExit(2)
    sys.stderr.write("%s %d could not be pinned: %s\n" % (kind, pid, err))
    raise SystemExit(1)
try:
    # EVERY IDENTITY QUESTION IS ASKED AFTER THE HANDLE IS HELD.  The
    # signal goes to the pinned process, so a number recycled before the
    # handle was taken can only make this REFUSE -- never mis-target.
    try:
        with open("/proc/%d/comm" % pid, "r", encoding="utf-8") as comm:
            observed = comm.read().strip()
    except OSError as err:
        sys.stderr.write("%s %d could not be identified: %s\n"
                         % (kind, pid, err))
        raise SystemExit(1)
    if observed != kind:
        sys.stderr.write("%d is %r and not %r\n" % (pid, observed, kind))
        raise SystemExit(1)
    try:
        owner = os.stat("/proc/%d" % pid).st_uid
    except OSError as err:
        sys.stderr.write("%s %d could not be examined: %s\n"
                         % (kind, pid, err))
        raise SystemExit(1)
    if owner != os.geteuid():
        sys.stderr.write("%s %d is owned by uid %d and this run is uid "
                         "%d\n" % (kind, pid, owner, os.geteuid()))
        raise SystemExit(1)
    try:
        sender(handle, getattr(signal, name))
    except OSError as err:
        sys.stderr.write("%s %d was not signalled: %s\n"
                         % (kind, pid, err))
        raise SystemExit(1)
finally:
    os.close(handle)
' "${kind}" "${pid}" "${signal}"
}

# playthrough_pid_is KIND PID
#   True when PID is alive and its executable name is KIND.  /proc is read
#   directly because `ps` is not in the pipeline's tool contract and an
#   ownership check that needs a package to be installed is one more thing that
#   can silently not happen.
playthrough_pid_is() {
    local kind="${1-}" pid="${2-}" comm=""
    case "${pid}" in
        ''|*[!0-9]*) return 1 ;;
    esac
    [ -d "/proc/${pid}" ] || return 1
    comm="$(cat "/proc/${pid}/comm" 2>/dev/null || true)"
    [ "${comm}" = "${kind}" ]
}

# playthrough_proc_uid PID
#   The real uid of a running process, from /proc/PID/status, or nothing.
playthrough_proc_uid() {
    local pid="${1-}" value=""
    case "${pid}" in
        ''|*[!0-9]*) return 1 ;;
    esac
    while IFS= read -r line; do
        case "${line}" in
            Uid:*)
                # Uid: real effective saved fs -- the real uid is first.
                # shellcheck disable=SC2086
                set -- ${line#Uid:}
                value="${1-}"
                break
                ;;
        esac
    done <"/proc/${pid}/status" 2>/dev/null || return 1
    case "${value}" in
        ''|*[!0-9]*) return 1 ;;
    esac
    printf '%s' "${value}"
    return 0
}

# playthrough_proc_cmdline PID
#   The process's argument vector as one printable line, or nothing.
playthrough_proc_cmdline() {
    local pid="${1-}" text=""
    case "${pid}" in
        ''|*[!0-9]*) return 1 ;;
    esac
    text="$(tr '\0' ' ' <"/proc/${pid}/cmdline" 2>/dev/null || true)"
    [ -n "${text}" ] || return 1
    text="${text%"${text##*[![:space:]]}"}"
    case "${text}" in
        *[[:cntrl:]]*) return 1 ;;
    esac
    # Bounded, because this is a diagnostic field and an unbounded one
    # would let a long argument vector dominate the record.
    printf '%s' "${text:0:240}"
    return 0
}

# playthrough_pid_identity PID
#   Print a process's full identity as ONE line, or nothing:
#
#     <comm> <starttime> <uid> <resolved exe> <cmdline>
#
#   All five, because each closes a hole the others leave open: comm is
#   forgeable by any process that renames itself, (pid, starttime) is
#   unique for the life of a boot and so defeats pid recycling, the uid
#   says whose process it is, the resolved executable says WHICH Xvfb,
#   and the argument vector carries the display it was asked for.  One
#   line, so a caller compares it whole rather than partly by accident.
playthrough_pid_identity() {
    local pid="${1-}" comm="" started="" uid="" exe="" cmd=""
    case "${pid}" in
        ''|*[!0-9]*) return 1 ;;
    esac
    [ -d "/proc/${pid}" ] || return 1
    comm="$(cat "/proc/${pid}/comm" 2>/dev/null || true)"
    started="$(playthrough_proc_start_time "${pid}")" || return 1
    uid="$(playthrough_proc_uid "${pid}")" || return 1
    # readlink rather than a shell test: /proc/PID/exe is a symlink to the
    # backing file, so this reports the program that is RUNNING even when
    # the name it was invoked under has since been replaced on disk.
    exe="$(readlink -f "/proc/${pid}/exe" 2>/dev/null || true)"
    cmd="$(playthrough_proc_cmdline "${pid}")" || cmd="-"
    [ -n "${comm}" ] || return 1
    [ -n "${exe}" ] || exe="-"
    printf '%s %s %s %s %s' "${comm}" "${started}" "${uid}" "${exe}" \
        "${cmd}"
    return 0
}

# playthrough_x_socket_identity
#   The device and inode of the contracted display's unix socket, or
#   nothing.
playthrough_x_socket_identity() {
    local socket="/tmp/.X11-unix/X${PLAYTHROUGH_DISPLAY_NUM}"
    local value=""
    [ -e "${socket}" ] || return 1
    value="$(find "${socket}" -maxdepth 0 -printf '%D:%i' 2>/dev/null \
        || true)"
    case "${value}" in
        ''|*[!0-9:]*) return 1 ;;
    esac
    printf '%s' "${value}"
    return 0
}

# playthrough_record_x_ownership KIND [PID]
#   Record that this checkout brought the contracted display up.  KIND is
#   'pipeline' for a server this shell's process tree owns, or 'supervisor' for
#   the provisioned durable service, which this checkout asked for and can
#   restart.
playthrough_record_x_ownership() {
    local kind="${1:-pipeline}"
    local pid="${2-}"
    local record identity="" socket="" cookie=""
    record="$(playthrough_x_ownership_record)"
    # THE IDENTITY IS READ BEFORE THE FILE IS CREATED, so a refusal leaves
    # nothing behind at all.
    if [ -n "${pid}" ]; then
        identity="$(playthrough_pid_identity "${pid}")" || identity=""
        if [ -z "${identity}" ]; then
            # A pipeline-owned server whose identity cannot be read is not
            # recordable: the record would then claim an ownership no later run
            # could check, which is worse than no record at all (a missing
            # record degrades the trust state, and a false one would not).
            playthrough_die "the X server pid '${pid}' has no readable" \
                "identity in /proc, so this checkout's ownership of" \
                "${PLAYTHROUGH_DISPLAY} cannot be recorded in a form" \
                "any later run could verify.  Nothing was recorded."
            return 1
        fi
    fi
    socket="$(playthrough_x_socket_identity)" || socket="-"
    cookie="$(playthrough_xauth_digest)" || cookie="-"
    playthrough_secure_file "${record}" 600 \
        "the X ownership record" || return 1
    {
        printf 'display=%s\n' "${PLAYTHROUGH_DISPLAY}"
        printf 'kind=%s\n' "${kind}"
        printf 'pid=%s\n' "${pid}"
        printf 'repo=%s\n' "${PLAYTHROUGH_REPO_ROOT}"
        printf 'screen=%s\n' "${PLAYTHROUGH_SCREEN}"
        printf 'authority=%s\n' "${PLAYTHROUGH_XAUTHORITY_ORIGIN}"
        printf 'identity=%s\n' "${identity:--}"
        printf 'socket=%s\n' "${socket}"
        printf 'cookie=%s\n' "${cookie}"
        printf 'recorded=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    } >"${record}" || {
        playthrough_die "cannot write the X ownership record" \
            "'${record}'"
        return 1
    }
    return 0
}

# playthrough_x_ownership_state
#   Print one word about the contracted display and return 0 only when
#   this checkout owns it:
#
#     pipeline    this checkout started it; the recorded pid is alive
#                 and is an Xvfb process
#     supervisor  the provisioned durable service serves it here
#     stale       a record exists and the process it names is gone
#     replaced    the recorded process is alive, but the identity, the
#                 socket or the cookie no longer match the record
#     foreign     something is answering and no record claims it
#     absent      nothing is answering
#
#   REPLACED IS REPORTED SEPARATELY FROM STALE because the two send an
#   operator to different places, and collapsing them into "not ours"
#   would hide the case a recycled pid produces.  Neither is `pipeline`,
#   so both are refusals.  PLAYTHROUGH_X_OWNERSHIP_REASON carries which
#   field disagreed; read it as a variable, never through command
#   substitution, which would run this in a subshell and lose it.
export PLAYTHROUGH_X_OWNERSHIP_REASON=""
export PLAYTHROUGH_X_OWNERSHIP_STATE=""

playthrough_x_ownership_state() {
    local record recorded_display="" recorded_kind="" recorded_pid=""
    local recorded_repo="" recorded_identity="" recorded_socket=""
    local recorded_cookie="" line
    local identity="" socket="" cookie=""
    PLAYTHROUGH_X_OWNERSHIP_REASON=""
    PLAYTHROUGH_X_OWNERSHIP_STATE=""
    if ! playthrough_display_ready >/dev/null 2>&1; then
        PLAYTHROUGH_X_OWNERSHIP_STATE="absent"
        printf '%s' "absent"
        return 1
    fi
    record="$(playthrough_x_ownership_record)"
    if [ ! -f "${record}" ]; then
        PLAYTHROUGH_X_OWNERSHIP_REASON="no ownership record exists for \
${PLAYTHROUGH_DISPLAY}, so nothing claims the server that is answering"
        PLAYTHROUGH_X_OWNERSHIP_STATE="foreign"
        printf '%s' "foreign"
        return 1
    fi
    while IFS= read -r line; do
        case "${line}" in
            display=*) recorded_display="${line#display=}" ;;
            kind=*) recorded_kind="${line#kind=}" ;;
            pid=*) recorded_pid="${line#pid=}" ;;
            repo=*) recorded_repo="${line#repo=}" ;;
            identity=*) recorded_identity="${line#identity=}" ;;
            socket=*) recorded_socket="${line#socket=}" ;;
            cookie=*) recorded_cookie="${line#cookie=}" ;;
        esac
    done <"${record}"
    if [ "${recorded_display}" != "${PLAYTHROUGH_DISPLAY}" ] ||
       [ "${recorded_repo}" != "${PLAYTHROUGH_REPO_ROOT}" ]; then
        PLAYTHROUGH_X_OWNERSHIP_REASON="the record names display \
'${recorded_display}' for checkout '${recorded_repo}', and this run is \
${PLAYTHROUGH_DISPLAY} for ${PLAYTHROUGH_REPO_ROOT}"
        PLAYTHROUGH_X_OWNERSHIP_STATE="foreign"
        printf '%s' "foreign"
        return 1
    fi
    case "${recorded_kind}" in
        supervisor)
            PLAYTHROUGH_X_OWNERSHIP_STATE="supervisor"
        printf '%s' "supervisor"
            return 0
            ;;
        pipeline)
            if ! playthrough_pid_is Xvfb "${recorded_pid}"; then
                PLAYTHROUGH_X_OWNERSHIP_REASON="the recorded pid \
${recorded_pid:-<none>} is not a live Xvfb, so the server that was \
recorded is gone"
                PLAYTHROUGH_X_OWNERSHIP_STATE="stale"
        printf '%s' "stale"
                return 1
            fi
            # A RECORD WITHOUT AN IDENTITY IS NOT TRUSTED: 'pid N is
            # called Xvfb' is forgeable, so a record that carries no
            # full identity cannot establish ownership.
            if [ -z "${recorded_identity}" ] ||
               [ "${recorded_identity}" = "-" ]; then
                PLAYTHROUGH_X_OWNERSHIP_REASON="the record carries no \
process identity, so 'pid ${recorded_pid} is called Xvfb' is the only \
claim in it and a recycled pid would satisfy that"
                PLAYTHROUGH_X_OWNERSHIP_STATE="replaced"
        printf '%s' "replaced"
                return 1
            fi
            identity="$(playthrough_pid_identity "${recorded_pid}")" ||
                identity=""
            if [ "${identity}" != "${recorded_identity}" ]; then
                PLAYTHROUGH_X_OWNERSHIP_REASON="pid ${recorded_pid} is \
alive but is not the process that was recorded: recorded \
'${recorded_identity}', found '${identity:-<unreadable>}'"
                PLAYTHROUGH_X_OWNERSHIP_STATE="replaced"
        printf '%s' "replaced"
                return 1
            fi
            # THE SOCKET, WHICH IS THE DISPLAY'S OWN IDENTITY.  A server
            # that died and was replaced leaves a new inode behind, and
            # the pid check cannot see that at all.
            if [ -n "${recorded_socket}" ] &&
               [ "${recorded_socket}" != "-" ]; then
                socket="$(playthrough_x_socket_identity)" || socket=""
                if [ "${socket}" != "${recorded_socket}" ]; then
                    PLAYTHROUGH_X_OWNERSHIP_REASON="the socket for \
${PLAYTHROUGH_DISPLAY} is ${socket:-<absent>} and the recorded server \
created ${recorded_socket}, so what a client reaches now is not what was \
recorded"
                    PLAYTHROUGH_X_OWNERSHIP_STATE="replaced"
        printf '%s' "replaced"
                    return 1
                fi
            fi
            # AND THE COOKIE THE SERVER WAS STARTED WITH, because a
            # rotated authority file means clients now reach the display
            # with a credential this record never saw.
            if [ -n "${recorded_cookie}" ] &&
               [ "${recorded_cookie}" != "-" ]; then
                cookie="$(playthrough_xauth_digest)" || cookie=""
                if [ "${cookie}" != "${recorded_cookie}" ]; then
                    PLAYTHROUGH_X_OWNERSHIP_REASON="the authority file \
now holds cookie ${cookie:-<none>} for ${PLAYTHROUGH_DISPLAY} and the \
recorded server was started with ${recorded_cookie}"
                    PLAYTHROUGH_X_OWNERSHIP_STATE="replaced"
        printf '%s' "replaced"
                    return 1
                fi
            fi
            PLAYTHROUGH_X_OWNERSHIP_STATE="pipeline"
        printf '%s' "pipeline"
            return 0
            ;;
    esac
    PLAYTHROUGH_X_OWNERSHIP_REASON="the record names kind \
'${recorded_kind}', which is neither 'pipeline' nor 'supervisor'"
    printf '%s' "foreign"
    return 1
}

# playthrough_assert_x_ownership
#   Establish ownership or register the inability to.  Never fatal on its own:
#   the refusal belongs to the capture gate, which reads the trust state, so
#   that diagnosis on a foreign display keeps working while nothing recorded on
#   one can be mistaken for evidence.
playthrough_assert_x_ownership() {
    local state
    # NOT `$( )`: the reason is set INSIDE the function, and a command
    # substitution would run it in a subshell where every variable it sets
    # dies.
    if playthrough_x_ownership_state >/dev/null; then
        state="${PLAYTHROUGH_X_OWNERSHIP_STATE}"
        playthrough_log "the display ${PLAYTHROUGH_DISPLAY} is owned" \
            "by this checkout (${state})"
        return 0
    fi
    state="${PLAYTHROUGH_X_OWNERSHIP_STATE}"
    local why="${PLAYTHROUGH_X_OWNERSHIP_REASON:-no detail was \
recorded}"
    case "${state}" in
        absent)
            return 1
            ;;
        stale)
            playthrough_trust_unverifiable "the X server answering \
${PLAYTHROUGH_DISPLAY} is not the one this checkout recorded starting \
(its pid is gone), so who owns the display cannot be established"
            playthrough_warn "the ownership record for" \
                "${PLAYTHROUGH_DISPLAY} names a process that is no" \
                "longer running, so the server answering now was not" \
                "started by this checkout: ${why}.  Diagnosis" \
                "continues; the trust state is held at diagnostic, so" \
                "no frame taken on this display can join the record." \
                "Run 'playthrough/tooling/launch_game.sh stop' and" \
                "bring the surface up again to own it."
            ;;
        replaced)
            # THE CASE A PID-AND-NAME CHECK CANNOT SEE: the pid is
            # alive and is an Xvfb, and is still not the server that was
            # recorded.
            playthrough_trust_unverifiable "a process is alive under \
the recorded X server pid and is not the process that was recorded, so \
what a client reaches on ${PLAYTHROUGH_DISPLAY} cannot be shown to be \
the server this checkout started"
            playthrough_warn "the ownership record for" \
                "${PLAYTHROUGH_DISPLAY} no longer describes what is" \
                "answering: ${why}.  This is not a stale record --" \
                "something IS there -- so it is reported separately." \
                "The trust state is held at diagnostic, so no frame" \
                "taken on this display can join the record.  Run" \
                "'playthrough/tooling/launch_game.sh stop' and bring" \
                "the surface up again to own it."
            ;;
        *)
            playthrough_trust_unverifiable "the X server answering \
${PLAYTHROUGH_DISPLAY} was not started by this checkout, so it cannot \
be shown to be free of other clients for the length of the session"
            playthrough_warn "${PLAYTHROUGH_DISPLAY} is served by" \
                "infrastructure this checkout did not start:" \
                "${why}.  It is fine to DIAGNOSE" \
                "against, and the trust state is held at diagnostic so" \
                "that nothing captured on it can join the record.  For" \
                "a recorded session, let this checkout own the" \
                "display: use a free CLONE_INDEX, or stop the foreign" \
                "server first."
            ;;
    esac
    return 1
}

# ---------------------------------------------------------------------
# THE RUNTIME ROOT IS A CACHE, AND A CACHE NEEDS A RETENTION RULE
# Everything under the private runtime root is diagnostic: lock files, pid
# files, the per-stage stderr captures, the scratch directories a gate opens.
# ---------------------------------------------------------------------

# playthrough_lock_is_held PATH
#   True when some process holds the advisory lock on PATH.  Asks the kernel
#   with a non-blocking flock in a subshell, so the answer costs nothing and
#   this shell never ends up holding the lock it asked about.
playthrough_lock_is_held() {
    local path="${1-}"
    [ -f "${path}" ] || return 1
    playthrough_require_tools flock >/dev/null 2>&1 || return 0
    if ( "${PLAYTHROUGH_BIN_FLOCK}" -n 9 ) 9>>"${path}" \
            >/dev/null 2>&1; then
        return 1
    fi
    return 0
}

# playthrough_path_in_use PATH
#   True when some live process has PATH, or anything beneath it, open --
#   as a descriptor or as its working directory.
playthrough_path_in_use() {
    local path="${1-}" link="" entry="" fd=""
    [ -n "${path}" ] || return 1
    [ -e "${path}" ] || return 1
    [ -d /proc ] || return 0
    for entry in /proc/[0-9]*; do
        [ -d "${entry}" ] || continue
        link="$(readlink "${entry}/cwd" 2>/dev/null || true)"
        if [ -n "${link}" ]; then
            case "${link}" in
                "${path}"|"${path}"/*) return 0 ;;
            esac
        fi
        for fd in "${entry}"/fd/*; do
            [ -e "${fd}" ] || continue
            link="$(readlink "${fd}" 2>/dev/null || true)"
            [ -n "${link}" ] || continue
            case "${link}" in
                "${path}"|"${path}"/*) return 0 ;;
            esac
        done
    done
    return 1
}

# playthrough_proc_start_time PID
#   Print the process's start time in clock ticks since boot -- field 22
#   of /proc/PID/stat -- or nothing.
playthrough_proc_start_time() {
    local pid="${1-}" line="" tail=""
    case "${pid}" in
        ''|*[!0-9]*) return 1 ;;
    esac
    line="$(cat "/proc/${pid}/stat" 2>/dev/null || true)"
    [ -n "${line}" ] || return 1
    tail="${line##*) }"
    # After the discard, field 3 (state) is first, so the start time --
    # field 22 -- is the 20th remaining token.
    # shellcheck disable=SC2086
    set -- ${tail}
    [ "$#" -ge 20 ] || return 1
    local value="${20}"
    case "${value}" in
        ''|*[!0-9]*) return 1 ;;
    esac
    printf '%s' "${value}"
    return 0
}

# playthrough_x_socket_state
#   Diagnose the display's UNIX socket, the one thing that can disagree
#   with "a server is answering":
#
#     serving   the socket exists and the server answers
#     stale     the socket exists and nothing answers -- an orphan of a
#               server that died without unlinking it
#     foreign   as `stale`, but owned by another account, so it is not
#               ours to reason about
#     absent    no socket
#
#   Reports and never removes; the caller decides what to say about it.
playthrough_x_socket_state() {
    local socket="/tmp/.X11-unix/X${PLAYTHROUGH_DISPLAY_NUM}"
    local owner=""
    if [ ! -e "${socket}" ]; then
        printf '%s' "absent"
        return 1
    fi
    if playthrough_display_probe; then
        printf '%s' "serving"
        return 0
    fi
    owner="$("${PLAYTHROUGH_UTIL_STAT}" -Lc '%u' -- "${socket}" \
        2>/dev/null || true)"
    if [ -n "${owner}" ] && [ "${owner}" != "${PLAYTHROUGH_UID}" ] &&
       [ "${owner}" != "0" ]; then
        printf '%s' "foreign"
        return 1
    fi
    printf '%s' "stale"
    return 1
}

# playthrough_diagnose_x_socket
#   The operator-facing form of the state above.  Called on the failure path of
#   a display wait, where "nothing is answering" is exactly the moment the
#   difference between no socket and an orphaned socket decides what to do
#   next.
playthrough_diagnose_x_socket() {
    local state
    state="$(playthrough_x_socket_state)" && return 0
    case "${state}" in
        stale)
            playthrough_warn "the socket for ${PLAYTHROUGH_DISPLAY}" \
                "(/tmp/.X11-unix/X${PLAYTHROUGH_DISPLAY_NUM})" \
                "exists but nothing answers on it: a server died" \
                "without unlinking it.  It is NOT removed here --" \
                "deleting a socket that is in fact live takes the" \
                "display away from a running session, and Xvfb" \
                "replaces the file itself when it starts.  If a" \
                "restart refuses with 'server already running', clear" \
                "the matching /tmp/.X${PLAYTHROUGH_DISPLAY_NUM}-lock" \
                "by hand after confirming no Xvfb process holds it."
            ;;
        foreign)
            playthrough_warn "the socket for ${PLAYTHROUGH_DISPLAY}" \
                "belongs to another account and nothing answers on" \
                "it, so this checkout can neither use nor clean it." \
                "Use a different CLONE_INDEX."
            ;;
        absent)
            playthrough_log "no socket for ${PLAYTHROUGH_DISPLAY}," \
                "so no server has run on it in this container"
            ;;
    esac
    return 1
}

# playthrough_prune_runtime
#   Remove this pipeline's own closed leftovers from the runtime root.  Bounded
#   by shape and by age, silent about what it keeps, and a no-op when `find` is
#   unavailable.
playthrough_holds_live_lock() {
    local directory="${1-}" candidate=""
    [ -d "${directory}" ] || return 1
    command -v find >/dev/null 2>&1 || return 0
    while IFS= read -r candidate; do
        [ -n "${candidate}" ] || continue
        if playthrough_lock_is_held "${candidate}"; then
            return 0
        fi
    done < <(find "${directory}" -maxdepth 1 -type f -name '*.lock' \
        2>/dev/null || true)
    return 1
}

# playthrough_unresolved_journals DIRECTORY
#   Print the names of the journal files DIRECTORY still holds, space
#   separated, or nothing.  The set is exact -- session.py's `step.json`
playthrough_unresolved_journals() {
    local directory="${1-}" found=""
    [ -d "${directory}" ] || return 0
    command -v find >/dev/null 2>&1 || return 0
    found="$(find "${directory}" -maxdepth 1 -type f \
        \( -name 'step.json' -o -name '*.generation.json' \) \
        -printf '%f ' 2>/dev/null || true)"
    printf '%s' "${found% }"
    return 0
}

playthrough_prune_runtime() {
    local minutes="${PLAYTHROUGH_RUNTIME_RETENTION_MINUTES:-1440}"
    playthrough_validate_int "${minutes}" \
        "the runtime retention window" 1 525600 >/dev/null 2>&1 ||
        return 0
    minutes="${PLAYTHROUGH_INT}"
    command -v find >/dev/null 2>&1 || return 0
    local path removed=0 pid="" journals=""
    # 1  CLOSED LOCK FILES.  Held ones are kept, and proving which is
    #    which is the diagnosis this used not to have.
    while IFS= read -r path; do
        [ -n "${path}" ] || continue
        if playthrough_lock_is_held "${path}"; then
            continue
        fi
        if playthrough_path_in_use "${path}"; then
            continue
        fi
        rm -f -- "${path}" 2>/dev/null && removed=$(( removed + 1 ))
    done < <(find "${PLAYTHROUGH_LOCK_DIR}" -maxdepth 1 -type f \
        -name '*.lock' -mmin "+${minutes}" 2>/dev/null || true)
    # 2  ORPHANED PER-STAGE STDERR CAPTURES.  Named for the pid that
    #    wrote them, which is what makes them identifiable and what makes
    #    them useless once that pid is gone -- so the pid is CHECKED
    while IFS= read -r path; do
        [ -n "${path}" ] || continue
        pid="${path##*/capture-stage-}"
        pid="${pid%.err}"
        case "${pid}" in
            ''|*[!0-9]*) ;;
            *)
                if [ -d "/proc/${pid}" ]; then
                    continue
                fi
                ;;
        esac
        if playthrough_path_in_use "${path}"; then
            continue
        fi
        rm -f -- "${path}" 2>/dev/null && removed=$(( removed + 1 ))
    done < <(find "${PLAYTHROUGH_RUNTIME_DIR}" -maxdepth 1 -type f \
        -name 'capture-stage-*.err' -mmin "+${minutes}" \
        2>/dev/null || true)
    # 3  SCRATCH DIRECTORIES a gate, a sequencer or a test left behind.
    #    THE LIST IS EVERY PREFIX THIS TREE CREATES WITH mktemp -d, and
    #    it has to stay that way: a stage that makes a scratch directory
    while IFS= read -r path; do
        [ -n "${path}" ] || continue
        if playthrough_path_in_use "${path}"; then
            continue
        fi
        if playthrough_holds_live_lock "${path}"; then
            continue
        fi
        journals="$(playthrough_unresolved_journals "${path}")"
        if [ -n "${journals}" ]; then
            # The path is passed raw: every message from these helpers
            # goes through playthrough_redact, which rewrites the runtime
            # root to '<runtime>' -- whereas playthrough_rel, which is
            # about paths INSIDE the checkout, would render a runtime path
            # as '<outside the checkout>/...' and drop the one piece of
            # context an operator needs to find it.
            playthrough_warn "the scratch directory" \
                "'${path}' has been idle for more" \
                "than ${minutes} minute(s) but still holds an" \
                "unresolved journal (${journals}), so it is KEPT.  A" \
                "journal describes an evidence transaction that was" \
                "interrupted -- a keystroke that may have been" \
                "delivered, or a publication caught mid-switch -- and" \
                "deleting it would leave nothing able to say which." \
                "Reconcile it deliberately and this pruner will clear" \
                "what is left."
            continue
        fi
        rm -rf -- "${path}" 2>/dev/null && removed=$(( removed + 1 ))
    done < <(find "${PLAYTHROUGH_RUNTIME_DIR}" -maxdepth 1 -type d \
        \( -name 'verify.*' -o -name 'lock-*' -o -name 'session-*' \
           -o -name 'pipeline-*' \) \
        -mmin "+${minutes}" 2>/dev/null || true)
    if [ "${removed}" -gt 0 ]; then
        playthrough_log "pruned ${removed} closed leftover(s) older" \
            "than ${minutes} minute(s) from the runtime root; live" \
            "locks, pid files, the X cookie and every rejected frame" \
            "were left untouched"
    fi
    return 0
}

# playthrough_headless_down
#   Stop the headless surface THIS CHECKOUT owns, and nothing else.
playthrough_headless_down() {
    local state pid stopped=0
    # Read without a subshell, for the reason given in
    # playthrough_assert_x_ownership: the detail lives in a variable.
    playthrough_x_ownership_state >/dev/null || true
    state="${PLAYTHROUGH_X_OWNERSHIP_STATE}"
    case "${state}" in
        pipeline) ;;
        supervisor)
            playthrough_warn "the display ${PLAYTHROUGH_DISPLAY} is" \
                "served by the provisioned durable service" \
                "(${PLAYTHROUGH_SUPERVISED_X_UNITS}), which outlives" \
                "this pipeline by design.  Stop it with supervisorctl" \
                "if that is really what you want."
            return 0
            ;;
        absent)
            playthrough_log "nothing is answering on" \
                "${PLAYTHROUGH_DISPLAY}; there is nothing to stop"
            rm -f -- "$(playthrough_x_ownership_record)" 2>/dev/null ||
                true
            return 0
            ;;
        *)
            # `stale`, `replaced` and `foreign` all land here, and all three
            # mean the same thing for a TEARDOWN: this checkout cannot show
            # that what is answering is its own.
            playthrough_warn "the display ${PLAYTHROUGH_DISPLAY} was" \
                "not started by this checkout (${state}:" \
                "${PLAYTHROUGH_X_OWNERSHIP_REASON:-no detail was" \
                "recorded}), so it is left running.  Stopping" \
                "infrastructure this pipeline does not own would take" \
                "the display away from whoever does."
            return 1
            ;;
    esac
    # NOTHING IS SIGNALLED ON THE STRENGTH OF A PIDFILE: a recorded
    # number is a claim, and as root a recycled one is somebody else's
    # process.  The identity is proved first, then signalled by handle.
    local kind="" expected="" refusal="" signalled=0
    for pid in \
        "$(cat "${PLAYTHROUGH_WM_PIDFILE}" 2>/dev/null || true)" \
        "$(cat "${PLAYTHROUGH_XVFB_PIDFILE}" 2>/dev/null || true)"; do
        case "${pid}" in
            ''|*[!0-9]*) continue ;;
        esac
        [ -d "/proc/${pid}" ] || continue
        # The window pid file is written first, so the loop order fixes
        # which program each number is supposed to be.
        if [ -z "${kind}" ]; then
            kind="openbox"
        else
            kind="Xvfb"
        fi
        if ! playthrough_pid_is "${kind}" "${pid}"; then
            playthrough_warn "the pid file for ${kind} names ${pid}," \
                "and that process is alive and is not ${kind}" \
                "($(cat "/proc/${pid}/comm" 2>/dev/null || \
printf '<unreadable>')).  It was NOT signalled: the number was recycled" \
                "and killing whatever now holds it would be killing" \
                "somebody else's process."
            continue
        fi
        expected="$(playthrough_proc_uid "${pid}")" || expected=""
        if [ -n "${expected}" ] && [ "${expected}" != "$(id -u)" ]; then
            playthrough_warn "${kind} ${pid} is owned by uid" \
                "${expected} and this run is uid $(id -u), so it was" \
                "not started by this account and was NOT signalled."
            continue
        fi
        # `|| status=$?` rather than a bare assignment, so that a refusal
        # cannot end a caller running under `set -e`: a teardown that
        # aborts the script because ONE process could not be signalled
        # would leave the rest of the surface up.
        signalled=0
        refusal="$(playthrough_signal_pid "${kind}" "${pid}" SIGTERM \
            2>&1 >/dev/null)" || signalled=$?
        case "${signalled}" in
            0) stopped=$(( stopped + 1 )) ;;
            2)
                playthrough_warn "${kind} ${pid} was NOT signalled:" \
                    "${refusal:-pidfd signalling is unavailable}." \
                    "This pipeline signals a process through a handle" \
                    "rather than through its number, because a number" \
                    "can be recycled between the check and the signal" \
                    "and this runs as root.  Stop it by hand:" \
                    "kill ${pid}."
                ;;
            *)
                playthrough_warn "${kind} ${pid} was NOT signalled:" \
                    "${refusal:-no detail was reported}."
                ;;
        esac
    done
    playthrough_log "stopped ${stopped} process(es) of the headless" \
        "surface this checkout owns on ${PLAYTHROUGH_DISPLAY}; the" \
        "X socket is left for the server to unlink"
    rm -f -- "$(playthrough_x_ownership_record)" 2>/dev/null || true
    playthrough_prune_runtime
    return 0
}

# playthrough_assert_x_access_control
#   Prove, by trying it, that a client without the cookie CANNOT reach
#   this display.
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
#   Start openbox only if no window manager is present.  A bare X server has no
#   focus model, and xdotool key delivery to an unfocused window is unreliable,
#   so the WM is load-bearing for one-keystroke-per-frame capture rather than
#   cosmetic.
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
#   Assert the root window really is the contracted geometry and depth.
#   Capture targets the root, so a wrong size here would silently produce a
#   movie at the wrong resolution.
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
#   Bring the whole headless surface up idempotently and verify it: platform
#   support, video driver, X server, window manager, ACCESS CONTROL, geometry.
playthrough_headless_up() {
    playthrough_check_platform || return 1
    playthrough_check_path_ancestry || return 1
    playthrough_assert_video_driver || return 1
    playthrough_require_tools xdpyinfo xprop grep awk || return 1
    playthrough_start_xvfb || return 1
    playthrough_start_wm || return 1
    playthrough_assert_x_access_control || return 1
    # WHO OWNS THE DISPLAY, asked after the server is up and before anything is
    # launched on it.
    playthrough_assert_x_ownership || true
    playthrough_assert_display || return 1
    # BOUNDED RETENTION, once per launch rather than at source time.
    playthrough_prune_runtime
    return 0
}

# playthrough_mkdirs
#   Create the artifact directories.  Called explicitly, never at
#   source time: sourcing this file must not write into the tree.
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
        playthrough_deny_foreign_write "${dir}" \
            "artifact directory" || return 1
    done
    return 0
}

# playthrough_deny_foreign_write PATH [LABEL]
#   Take group and other WRITE access off PATH, announce it if it had
#   any, and confirm the result.  Read access is left exactly as it was.
playthrough_deny_foreign_write() {
    local path="${1-}"
    local label="${2:-${1-}}"
    local before after
    [ -n "${path}" ] || return 1
    playthrough_assert_utilities \
        "tightening '${path}'" || return 1
    before="$(playthrough_permission_bits "${path}")" || {
        playthrough_die "cannot read the mode of ${label} '${path}'," \
            "so whether other accounts can write to the evidence" \
            "cannot be established"
        return 1
    }
    if [ $(( 8#${before} & 8#022 )) -eq 0 ]; then
        return 0
    fi
    if ! "${PLAYTHROUGH_UTIL_CHMOD}" go-w -- "${path}"; then
        playthrough_die "cannot take group and other write access off" \
            "${label} '${path}' (mode ${before})"
        return 1
    fi
    after="$(playthrough_permission_bits "${path}")" || after=""
    if [ -z "${after}" ] || [ $(( 8#${after} & 8#022 )) -ne 0 ]; then
        playthrough_die "${label} '${path}' is still mode" \
            "'${after:-unreadable}' after chmod go-w, so it remains" \
            "writable by accounts other than its owner"
        return 1
    fi
    playthrough_warn "${label} '${path}' was mode ${before} --" \
        "writable by group or other -- and has been tightened to" \
        "${after}.  Anything written there while it was open could" \
        "have been rewritten or deleted by another local account, so" \
        "this is reported rather than repaired in silence"
    return 0
}

# playthrough_checkout_lock_name BASENAME
#   BASENAME with a short digest of THIS CHECKOUT's root appended, so a lock
#   taken under it excludes a second run over the same working tree and nothing
#   else.
playthrough_checkout_lock_name() {
    local base="${1-}"
    case "${base}" in
        ''|*[!a-z0-9_-]*)
            playthrough_die "'${base}' is not a usable lock basename" \
                "(lowercase letters, digits, '-' and '_' only)"
            return 1
            ;;
    esac
    playthrough_require_tools sha256sum || return 1
    local digest=""
    digest="$(printf '%s' "${PLAYTHROUGH_REPO_ROOT}" |
        "${PLAYTHROUGH_BIN_SHA256SUM}" 2>/dev/null || printf '')"
    digest="${digest%% *}"
    case "${digest}" in
        ''|*[!0-9a-f]*)
            playthrough_die "the checkout digest for the '${base}'" \
                "lock could not be computed, so a lock name that" \
                "names this working tree cannot be built"
            return 1
            ;;
    esac
    printf '%s-%s' "${base}" "${digest:0:8}"
    return 0
}

# playthrough_acquire_lock NAME [TIMEOUT_SECONDS] [MODE]
#   Take an advisory lock and leave its descriptor in
#   PLAYTHROUGH_LOCK_FD.
PLAYTHROUGH_CHILD_CLOSE_FD=""
PLAYTHROUGH_CHILD_CLOSE_BORROWED=0
PLAYTHROUGH_CHILD_CLOSE_FD2=""
PLAYTHROUGH_CHILD_CLOSE_BORROWED2=0

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
    local mode="${3:-exclusive}" flag=""
    case "${mode}" in
        exclusive) flag="-x" ;;
        shared) flag="-s" ;;
        *)
            playthrough_die "'${mode}' is not a lock mode; the only" \
                "two are 'exclusive' (nothing else may hold it) and" \
                "'shared' (other shared holders are welcome, exclusive" \
                "ones are not)"
            return 1
            ;;
    esac
    playthrough_require_tools flock || return 1
    local path="${PLAYTHROUGH_LOCK_DIR}/${name}.lock"
    playthrough_secure_file "${path}" 600 || return 1
    local fd
    if ! exec {fd}>>"${path}"; then
        playthrough_die "cannot open the '${name}' lock at ${path}"
        return 1
    fi
    if ! flock "${flag}" -w "${timeout}" "${fd}"; then
        exec {fd}>&-
        playthrough_die "another process has held the '${name}' lock" \
            "against an acquisition of it as '${mode}' for more than" \
            "${timeout}s (${path}).  Two stages working over one" \
            "checkout at once would corrupt what they share, so this" \
            "one stops rather than racing it."
        return 1
    fi
    PLAYTHROUGH_LOCK_FD="${fd}"
    return 0
}

# playthrough_child_close_fd / playthrough_child_close_done
#   Make it safe to detach a long-lived child while a lock is held.
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
    PLAYTHROUGH_CHILD_CLOSE_FD2="${PLAYTHROUGH_MUTATION_LOCK_FD:-}"
    PLAYTHROUGH_CHILD_CLOSE_BORROWED2=0
    case "${PLAYTHROUGH_CHILD_CLOSE_FD2}" in
        ''|*[!0-9]*)
            if ! exec {PLAYTHROUGH_CHILD_CLOSE_FD2}</dev/null; then
                playthrough_die "cannot open a second descriptor to" \
                    "withhold from a detached child"
                return 1
            fi
            PLAYTHROUGH_CHILD_CLOSE_BORROWED2=1
            ;;
    esac
    return 0
}

# playthrough_child_close_done
#   Give back the borrowed descriptor.
playthrough_child_close_done() {
    if [ "${PLAYTHROUGH_CHILD_CLOSE_BORROWED:-0}" = "1" ]; then
        case "${PLAYTHROUGH_CHILD_CLOSE_FD:-}" in
            ''|*[!0-9]*) ;;
            *)
                if [ -e "/proc/self/fd/${PLAYTHROUGH_CHILD_CLOSE_FD}" ]
                then
                    exec {PLAYTHROUGH_CHILD_CLOSE_FD}>&-
                fi
                ;;
        esac
    fi
    if [ "${PLAYTHROUGH_CHILD_CLOSE_BORROWED2:-0}" = "1" ]; then
        case "${PLAYTHROUGH_CHILD_CLOSE_FD2:-}" in
            ''|*[!0-9]*) ;;
            *)
                if [ -e "/proc/self/fd/${PLAYTHROUGH_CHILD_CLOSE_FD2}" ]
                then
                    exec {PLAYTHROUGH_CHILD_CLOSE_FD2}>&-
                fi
                ;;
        esac
    fi
    PLAYTHROUGH_CHILD_CLOSE_FD=""
    PLAYTHROUGH_CHILD_CLOSE_BORROWED=0
    PLAYTHROUGH_CHILD_CLOSE_FD2=""
    PLAYTHROUGH_CHILD_CLOSE_BORROWED2=0
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
    # THE SAME TRAP as playthrough_child_close_done documents at length: `exec
    # {fd}>&- 2>/dev/null` sends this shell's stderr to /dev/null for good, so
    # a script that released its lock and then had something to report reported
    # it into the void.
    if [ -e "/proc/self/fd/${fd}" ]; then
        exec {fd}>&-
    fi
    if [ "${fd}" = "${PLAYTHROUGH_LOCK_FD:-}" ]; then
        PLAYTHROUGH_LOCK_FD=""
    fi
    return 0
}

# ---------------------------------------------------------------------
# THE MUTATION LOCK -- ONE LOCK THE WHOLE CHECKOUT AGREES ON
# Every lock above this line serialises ONE STAGE against another copy of
# ITSELF: two sequencers, two checkpoints, two launches, two publications of
# the same artifact.
# ---------------------------------------------------------------------

PLAYTHROUGH_MUTATION_LOCK_BASENAME="mutation"
# BOTH OF THESE ARE INITIALISED CONDITIONALLY, because that is the whole
# re-entrancy mechanism: a stage that already holds the lock re-sources
# this file and must keep the descriptor it is holding.
PLAYTHROUGH_MUTATION_LOCK_FD="${PLAYTHROUGH_MUTATION_LOCK_FD:-}"
PLAYTHROUGH_MUTATION_LOCK_OWNED="${PLAYTHROUGH_MUTATION_LOCK_OWNED:-0}"
# How long to wait for the other role.  Generous, because a render or a
# long session legitimately holds it for minutes, and an unbounded wait
# is a hang nobody can diagnose.
PLAYTHROUGH_MUTATION_LOCK_TIMEOUT_DEFAULT=900

# playthrough_mutation_lock_path
#   This checkout's mutation lock file.  Derived from the same digest the
#   sequencer and the checkpoint locks use, so two clones do not contend and
#   two runs over one tree always do.
playthrough_mutation_lock_path() {
    local name=""
    name="$(playthrough_checkout_lock_name \
        "${PLAYTHROUGH_MUTATION_LOCK_BASENAME}")" || return 1
    printf '%s/%s.lock' "${PLAYTHROUGH_LOCK_DIR}" "${name}"
    return 0
}

# playthrough_mutation_lock_satisfies WANT HAVE
#   True when a lock already held in mode HAVE covers a request for mode
#   WANT.  Exclusive covers both; shared covers only shared.
playthrough_mutation_lock_satisfies() {
    case "${2-}:${1-}" in
        exclusive:exclusive|exclusive:shared|shared:shared) return 0 ;;
    esac
    return 1
}

# playthrough_mutation_lock_inherited MODE
#   0  an ancestor holds a lock that covers MODE, proved
#   1  nothing claims to hold one
#   2  something claims to and the claim did not hold up (diagnosed)
playthrough_mutation_lock_inherited() {
    local want="${1-}" have="${PLAYTHROUGH_MUTATION_LOCK_HELD:-}"
    local fd="${PLAYTHROUGH_MUTATION_LOCK_FD:-}" path="" link=""
    [ -n "${have}" ] || return 1
    case "${have}" in
        exclusive|shared) ;;
        *)
            playthrough_die "PLAYTHROUGH_MUTATION_LOCK_HELD is" \
                "'${have}', which is not a lock mode.  It is set by" \
                "playthrough_acquire_mutation_lock and read by every" \
                "stage this one starts; a value nothing produced means" \
                "the environment was edited, so this stage refuses" \
                "rather than deciding for itself whether the tree is" \
                "quiescent."
            return 2
            ;;
    esac
    if ! playthrough_mutation_lock_satisfies "${want}" "${have}"; then
        playthrough_die "this stage needs the mutation lock" \
            "${want}ly and an ancestor holds it ${have}ly.  A shared" \
            "hold does not make the tree quiescent -- another producer" \
            "may be writing under it right now -- and upgrading in" \
            "place deadlocks when two holders upgrade at once.  Run" \
            "this stage outside the shared window instead."
        return 2
    fi
    if ! path="$(playthrough_mutation_lock_path)"; then
        playthrough_die "an ancestor claims to hold the mutation lock" \
            "but this checkout's lock path could not be derived, so" \
            "the claim cannot be checked"
        return 2
    fi
    case "${fd}" in
        ''|*[!0-9]*)
            playthrough_die "an ancestor claims to hold the mutation" \
                "lock ${have}ly but PLAYTHROUGH_MUTATION_LOCK_FD is" \
                "'${fd}', so there is no descriptor to check the claim" \
                "against"
            return 2
            ;;
    esac
    link="$(readlink "/proc/self/fd/${fd}" 2>/dev/null || true)"
    if [ "${link}" != "${path}" ]; then
        playthrough_die "an ancestor claims to hold the mutation lock" \
            "on descriptor ${fd}, but that descriptor is" \
            "'${link:-not open}' rather than ${path}.  An inherited" \
            "descriptor is the only evidence a child has that its" \
            "parent holds the lock, and this one is not it."
        return 2
    fi
    if ! playthrough_lock_is_held "${path}"; then
        playthrough_die "an ancestor claims to hold the mutation lock" \
            "at ${path}, but the kernel says nothing holds it.  The" \
            "claim is stale or false; either way this stage will not" \
            "proceed as though the tree were quiescent."
        return 2
    fi
    return 0
}

# playthrough_acquire_mutation_lock MODE [TIMEOUT_SECONDS]
#   Take this checkout's mutation lock, or prove an ancestor already
#   holds one strong enough and do nothing.
playthrough_acquire_mutation_lock() {
    local mode="${1:-exclusive}" timeout="" name="" saved=""
    case "${mode}" in
        exclusive|shared) ;;
        *)
            playthrough_die "'${mode}' is not a mutation lock mode;" \
                "producers take it 'shared' and the verifier and the" \
                "committer take it 'exclusive'"
            return 1
            ;;
    esac
    timeout="${2:-${PLAYTHROUGH_MUTATION_LOCK_TIMEOUT:-\
${PLAYTHROUGH_MUTATION_LOCK_TIMEOUT_DEFAULT}}}"
    playthrough_validate_int "${timeout}" \
        "the mutation lock timeout" 0 86400 || return 1
    timeout="${PLAYTHROUGH_INT}"
    playthrough_mutation_lock_inherited "${mode}"
    case "$?" in
        0)
            playthrough_log "the mutation lock is already held" \
                "${PLAYTHROUGH_MUTATION_LOCK_HELD}ly by a verified" \
                "ancestor, so this stage inherits the quiescence it" \
                "would otherwise have taken for itself"
            return 0
            ;;
        2) return 1 ;;
    esac
    if ! name="$(playthrough_checkout_lock_name \
            "${PLAYTHROUGH_MUTATION_LOCK_BASENAME}")"; then
        playthrough_die "the mutation lock name for this checkout" \
            "could not be derived, so this stage cannot be kept apart" \
            "from a producer or a committer running over the same tree"
        return 1
    fi
    saved="${PLAYTHROUGH_LOCK_FD:-}"
    if ! playthrough_acquire_lock "${name}" "${timeout}" "${mode}"; then
        PLAYTHROUGH_LOCK_FD="${saved}"
        playthrough_die "the mutation lock '${name}' could not be" \
            "taken ${mode}ly within ${timeout}s.  Producers hold it" \
            "shared and the verifier and committer hold it exclusive," \
            "so this is a stage of the other kind still running over" \
            "THIS checkout -- wait for it rather than working beside it."
        return 1
    fi
    PLAYTHROUGH_MUTATION_LOCK_FD="${PLAYTHROUGH_LOCK_FD}"
    PLAYTHROUGH_MUTATION_LOCK_OWNED=1
    PLAYTHROUGH_LOCK_FD="${saved}"
    export PLAYTHROUGH_MUTATION_LOCK_HELD="${mode}"
    export PLAYTHROUGH_MUTATION_LOCK_FD
    playthrough_log "holding the mutation lock '${name}' ${mode}ly;" \
        "the digest in that name is derived from THIS checkout's path," \
        "so a stage running over a different working tree is not" \
        "serialised against this one"
    return 0
}

# playthrough_release_mutation_lock
#   Drop the mutation lock IF THIS SHELL TOOK IT.  A shell that merely
#   inherited an ancestor's hold releases nothing: releasing a lock this
#   process did not take would leave the ancestor believing it still had the
#   tree to itself, which is worse than never having locked at all.
playthrough_release_mutation_lock() {
    if [ "${PLAYTHROUGH_MUTATION_LOCK_OWNED:-0}" != "1" ]; then
        return 0
    fi
    PLAYTHROUGH_MUTATION_LOCK_OWNED=0
    playthrough_release_lock "${PLAYTHROUGH_MUTATION_LOCK_FD:-}" || true
    PLAYTHROUGH_MUTATION_LOCK_FD=""
    unset PLAYTHROUGH_MUTATION_LOCK_HELD
    return 0
}

# The platform source has exactly ONE reader, and it is
# playthrough_os_release_source below.

# playthrough_os_release KEY
#   Read one KEY=value out of the platform source, unquoted, or print nothing.
#   The file is PARSED rather than sourced: sourcing executes it, and a check
#   whose whole purpose is to reduce risk should not add an execution path of
#   its own.
playthrough_os_release() {
    case "${1-}" in
        ''|*[!A-Z_]*) return 1 ;;
    esac
    local source
    source="$(playthrough_os_release_source)"
    [ -r "${source}" ] || return 0
    sed -n "s/^${1}=//p" "${source}" |
        head -n 1 |
        tr -d '\042\047'
}

# playthrough_os_release_source
#   Which file the platform facts are read from, and the ONE case in
#   which it is not /etc/os-release.
playthrough_os_release_source() {
    local default="/etc/os-release"
    local nominated="${PLAYTHROUGH_OS_RELEASE-}"
    if [ -z "${nominated}" ] || [ "${nominated}" = "${default}" ]; then
        printf '%s' "${default}"
        return 0
    fi
    if [ -e "${PLAYTHROUGH_REPO_ROOT:-.}/.git" ]; then
        printf '%s' "${default}"
        return 0
    fi
    if [ -L "${nominated}" ]; then
        # A SYMLINK IS NOT EVIDENCE, even here. The verdict is read a moment
        # after this resolves, and a link can be repointed in between: what the
        # gate then measures is not what was nominated.
        printf '%s' "${default}"
        return 0
    fi
    if [ ! -f "${nominated}" ] || [ ! -r "${nominated}" ]; then
        printf '%s' "${default}"
        return 0
    fi
    printf '%s' "${nominated}"
    return 0
}

# playthrough_check_platform
#   Decide -- and by default REFUSE -- whether this host is still receiving
#   security fixes, because a version number is only as good as the archive
#   still publishing updates for it.

# playthrough_platform_waiver
#   The reason an out-of-support platform was accepted, or nothing.  Read at
#   every call rather than memoised, because a caller may set it after sourcing
#   this file.
playthrough_platform_waiver_max=160

playthrough_platform_waiver() {
    local value="${PLAYTHROUGH_ALLOW_EOL_PLATFORM-}"
    case "${value}" in
        ''|0)
            printf '%s' ""
            return 0
            ;;
    esac
    local clean=""
    # tr is not used: it is one more tool to require for a string
    # operation bash can do on its own, and this runs before the tool
    # inventory on some paths.
    local index=0 char=""
    while [ "${index}" -lt "${#value}" ]; do
        char="${value:${index}:1}"
        index=$(( index + 1 ))
        case "${char}" in
            [[:print:]]) clean="${clean}${char}" ;;
            *) clean="${clean} " ;;
        esac
    done
    while : ; do
        case "${clean}" in
            *"  "*) clean="${clean//  / }" ;;
            *) break ;;
        esac
    done
    # Leading and trailing space, without a subshell.
    clean="${clean#"${clean%%[![:space:]]*}"}"
    clean="${clean%"${clean##*[![:space:]]}"}"
    if [ "${#clean}" -gt "${playthrough_platform_waiver_max}" ]; then
        clean="${clean:0:${playthrough_platform_waiver_max}}..."
    fi
    if [ -z "${clean}" ]; then
        clean="(a waiver reason was set but contained no printable text)"
    fi
    if [ "${clean}" != "${value}" ] &&
       [ -z "${PLAYTHROUGH_PLATFORM_WAIVER_SANITISED:-}" ]; then
        export PLAYTHROUGH_PLATFORM_WAIVER_SANITISED=1
        playthrough_warn "the platform waiver reason contained" \
            "non-printable text or was longer than" \
            "${playthrough_platform_waiver_max} characters, so it is" \
            "recorded in its reduced one-line form.  A waiver reason" \
            "is published evidence: keep it to one short sentence and" \
            "put no secret and no host-identifying detail in it."
    fi
    printf '%s' "${clean}"
}

# playthrough_check_path_ancestry
#   Refuse a run whose own evidence or runtime state is reached through a
#   directory another local account may re-pave.  Returns 0 when both roads are
#   safe or the waiver is set, 1 when it refuses.
playthrough_check_path_ancestry() {
    local waiver="${PLAYTHROUGH_ALLOW_UNSAFE_PATH_ANCESTRY-}"
    local repo_unsafe=""
    if ! repo_unsafe="$(playthrough_untrusted_ancestor \
            "${PLAYTHROUGH_REPO_ROOT}")"; then
        repo_unsafe=""
    fi
    export PLAYTHROUGH_REPO_UNTRUSTED_ANCESTOR="${repo_unsafe}"
    if [ -z "${PLAYTHROUGH_RUNTIME_UNTRUSTED_ANCESTOR-}" ] &&
       [ -z "${repo_unsafe}" ]; then
        return 0
    fi
    local -a offenders=()
    if [ -n "${PLAYTHROUGH_RUNTIME_UNTRUSTED_ANCESTOR-}" ]; then
        offenders+=("the runtime anchor '${XDG_RUNTIME_DIR}' through \
'${PLAYTHROUGH_RUNTIME_UNTRUSTED_ANCESTOR}'")
    fi
    if [ -n "${repo_unsafe}" ]; then
        offenders+=("the checkout '${PLAYTHROUGH_REPO_ROOT}' through \
'${repo_unsafe}'")
    fi
    if [ -n "${waiver}" ] && [ "${waiver}" != "0" ]; then
        playthrough_warn "proceeding with an unsafe path ancestry" \
            "because PLAYTHROUGH_ALLOW_UNSAFE_PATH_ANCESTRY is set" \
            "(${waiver}): ${offenders[*]}.  Each of those is" \
            "group- or world-writable and NOT sticky, so any local" \
            "account may rename or replace a component of the path" \
            "between one check and the next use.  The trust state is" \
            "diagnostic for as long as this is set"
        playthrough_trust_refresh || true
        return 0
    fi
    playthrough_die "refusing to launch: ${offenders[*]}.  A" \
        "group- or world-writable directory WITHOUT the sticky bit" \
        "lets any account with write permission rename or unlink any" \
        "entry in it regardless of who owns it, so the mode of the" \
        "destination cannot make the PATH to it trustworthy.  For the" \
        "runtime anchor, remove it while no session is running so this" \
        "pipeline can re-anchor under the root-owned /run, or nominate" \
        "PLAYTHROUGH_XDG_ANCHOR at a directory whose whole ancestry is" \
        "owner- or root-controlled.  For the checkout, move it" \
        "somewhere with a safe road -- nothing here can relocate a" \
        "working tree.  To proceed anyway, set" \
        "PLAYTHROUGH_ALLOW_UNSAFE_PATH_ANCESTRY=<reason>, which is a" \
        "registered trust bypass and holds the trust state at" \
        "diagnostic."
    return 1
}

playthrough_check_platform() {
    # NOTHING HERE IS MEMOISED, AND THAT IS A FIX RATHER THAN A COST.
    local platform_source
    platform_source="$(playthrough_os_release_source)"
    export PLAYTHROUGH_PLATFORM_SOURCE="${platform_source}"
    if [ -n "${PLAYTHROUGH_OS_RELEASE-}" ] &&
       [ "${PLAYTHROUGH_OS_RELEASE}" != "${platform_source}" ] &&
       [ -z "${PLAYTHROUGH_OS_RELEASE_WARNED:-}" ]; then
        export PLAYTHROUGH_OS_RELEASE_WARNED=1
        if [ -e "${PLAYTHROUGH_REPO_ROOT:-.}/.git" ]; then
            playthrough_warn \
                "PLAYTHROUGH_OS_RELEASE='${PLAYTHROUGH_OS_RELEASE}' is" \
                "IGNORED: this repository root is a git working tree," \
                "so it can publish artifacts, and the platform facts" \
                "for a run that can publish are the host's own." \
                "Reading ${platform_source} instead.  If this host is" \
                "genuinely out of support, the only way past this check" \
                "is PLAYTHROUGH_ALLOW_EOL_PLATFORM=<reason>, which is a" \
                "registered trust bypass and refuses production" \
                "capture, render and mux."
        else
            playthrough_warn \
                "PLAYTHROUGH_OS_RELEASE='${PLAYTHROUGH_OS_RELEASE}' is" \
                "not a readable regular file, or is a symbolic link" \
                "(which can be repointed between this check and the" \
                "read, so it is never followed); reading" \
                "${platform_source} instead."
        fi
    fi
    {
        local id version pretty eol=""
        id="$(playthrough_os_release ID)"
        version="$(playthrough_os_release VERSION_ID)"
        pretty="$(playthrough_os_release PRETTY_NAME)"
        # From the distributions' own published support schedules.
        # Recheck it whenever this pipeline is next provisioned.
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
        if [ -z "${eol}" ]; then
            export PLAYTHROUGH_PLATFORM_SUPPORTED="unverified"
        else
            local today
            today="$(date -u +%Y-%m-%d)"
            # Both sides are ISO-8601, so a lexical comparison is a date
            # comparison; a table entry of "2031-04" compares as "2031-04" <
            # "2031-04-01", which errs towards refusing early rather than late.
            if [ "${today}" '>' "${eol}" ]; then
                export PLAYTHROUGH_PLATFORM_SUPPORTED="no"
            else
                export PLAYTHROUGH_PLATFORM_SUPPORTED="yes"
            fi
        fi
    }

    # The retired knob, answered rather than ignored.
    case "${PLAYTHROUGH_REQUIRE_SUPPORTED_PLATFORM-}" in
        ''|1) ;;
        *)
            if [ -z "${PLAYTHROUGH_PLATFORM_KNOB_WARNED:-}" ]; then
                export PLAYTHROUGH_PLATFORM_KNOB_WARNED=1
                playthrough_warn \
                    "PLAYTHROUGH_REQUIRE_SUPPORTED_PLATFORM=\
${PLAYTHROUGH_REQUIRE_SUPPORTED_PLATFORM} is" \
                    "set, and it no longer weakens this check: an" \
                    "out-of-support platform is refused by default" \
                    "now.  The only way past it is" \
                    "PLAYTHROUGH_ALLOW_EOL_PLATFORM=<reason>, which" \
                    "records the reason in the session's own contract."
            fi
            ;;
    esac

    local waiver
    waiver="$(playthrough_platform_waiver)"
    export PLAYTHROUGH_PLATFORM_WAIVER="${waiver}"

    if [ "${PLAYTHROUGH_PLATFORM_SUPPORTED}" = "yes" ]; then
        return 0
    fi

    local what remedy
    if [ "${PLAYTHROUGH_PLATFORM_SUPPORTED}" = "no" ]; then
        what="'${PLAYTHROUGH_PLATFORM}' reached end of life on \
${PLAYTHROUGH_PLATFORM_EOL}, so its ImageMagick, ffmpeg and Xorg/Xvfb \
packages receive no further security fixes, and all three parse \
untrusted-shaped input in this pipeline."
        remedy="Move the capture and render workload to a supported \
release -- Ubuntu 26.04 LTS is the migration target this pipeline is \
documented against -- and apply outstanding updates before recording."
    else
        what="cannot tell whether '${PLAYTHROUGH_PLATFORM}' is still \
receiving security updates: it is not in this pipeline's dated support \
table, and 'cannot tell' is not 'supported'."
        remedy="Either run on a release the table knows (Ubuntu 26.04 \
LTS, 24.04 LTS, Debian 13 or 12) or confirm this one is in support and \
fully patched and record that in the waiver."
    fi

    if [ -z "${waiver}" ]; then
        playthrough_die "refusing to run because ${what}  ${remedy}" \
            "If this host is the only one available, set" \
            "PLAYTHROUGH_ALLOW_EOL_PLATFORM to a short reason -- it is" \
            "warned once, exported as PLAYTHROUGH_PLATFORM_WAIVER and" \
            "printed in the environment summary, so a session" \
            "recorded under it says so in its own contract."
        return 1
    fi

    if [ -z "${PLAYTHROUGH_PLATFORM_WARNED:-}" ]; then
        export PLAYTHROUGH_PLATFORM_WARNED=1
        playthrough_warn "PROCEEDING UNDER A PLATFORM WAIVER:" \
            "${what}  The reason given is '${waiver}'.  ${remedy}" \
            "This is recorded in the environment summary and travels" \
            "with the session's contract.  The waiver is a" \
            "TRUST BYPASS: it moves the trust state to diagnostic, so" \
            "launch_game.sh will not start an instance to be captured" \
            "and capture.sh will not take a production frame.  It buys" \
            "diagnosis on this host, not evidence -- a compliant" \
            "capture has to run on a supported release."
    fi
    return 0
}

# playthrough_python [args ...]
#   Run the resolved interpreter, so no sibling has to rediscover it.  The
#   interpreter was verified at source time; this wrapper exists so that no
#   caller re-searches PATH and finds a different one.
playthrough_python() {
    "${PLAYTHROUGH_PYTHON}" "$@"
}

# playthrough_env_summary
#   Print the resolved contract on stdout.  Used by the direct execution path
#   below and worth logging at the head of a session, because it is the record
#   of what the capture actually ran under.
playthrough_env_summary() {
    # Resolve the platform verdict so the record carries it.
    playthrough_check_platform >/dev/null 2>&1 || true
    # The trust state is recomputed here for the same reason: this is the
    # record of what a session ran under, and "diagnostic" is the single most
    # important thing it can say.
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
        # WHICH FILE the platform facts came from.
        "PLAYTHROUGH_PLATFORM_SOURCE"
        "${PLAYTHROUGH_PLATFORM_SOURCE:-<unchecked>}"
        "PLAYTHROUGH_PLATFORM_SUPPORTED"
        "${PLAYTHROUGH_PLATFORM_SUPPORTED:-<unchecked>}"
        # The end-of-life date and the waiver reason travel with the
        # record because the platform gate is a REFUSAL by default: a
        # session that ran on an out-of-support host did so under a named
        # waiver, and the contract is where that has to be readable.
        "PLAYTHROUGH_PLATFORM_EOL"
        "${PLAYTHROUGH_PLATFORM_EOL:-<unchecked>}"
        "PLAYTHROUGH_PLATFORM_WAIVER"
        "${PLAYTHROUGH_PLATFORM_WAIVER:-<none>}"
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
        "PLAYTHROUGH_AMENDMENTS" "${PLAYTHROUGH_AMENDMENTS}"
        "PLAYTHROUGH_OBSERVATIONS" "${PLAYTHROUGH_OBSERVATIONS}"
        "PLAYTHROUGH_DATE_AUDIT" "${PLAYTHROUGH_DATE_AUDIT}"
        "PLAYTHROUGH_FRAME_DIGESTS" "${PLAYTHROUGH_FRAME_DIGESTS}"
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
        "PLAYTHROUGH_TRUST_UNVERIFIED"
        "${PLAYTHROUGH_TRUST_UNVERIFIED:-<none>}"
        "PLAYTHROUGH_RUNTIME_UNTRUSTED_ANCESTOR"
        "${PLAYTHROUGH_RUNTIME_UNTRUSTED_ANCESTOR:-<none>}"
    )
    printf '%s\n' "playthrough environment contract" || return 1
    # EVERY VALUE GOES THROUGH playthrough_redact, for the same reason every
    # diagnostic line does: this report is retained -- captured into logs,
    # quoted into reports, read by people who have no business knowing where
    # somebody else's clone lives -- and half of these fields are absolute
    # paths inside the checkout.
    local _playthrough_i=0
    local _playthrough_status=0
    while [ "${_playthrough_i}" -lt \
            "${#_playthrough_summary_fields[@]}" ]; do
        printf '  %-26s %s\n' \
            "${_playthrough_summary_fields[${_playthrough_i}]}" \
            "$(playthrough_redact \
                "${_playthrough_summary_fields[$((_playthrough_i + 1))]}")" ||
            _playthrough_status=1
        _playthrough_i=$((_playthrough_i + 2))
    done
    return "${_playthrough_status}"
}

# ---------------------------------------------------------------------
# THE ENCODER: pin imageio and MoviePy to the system ffmpeg
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
# ---------------------------------------------------------------------
if ! playthrough_assert_video_driver; then
    return 1 2>/dev/null || exit 1
fi

# The trust state is published at source time so that every consumer --
# including the Python stages, which read it out of the environment -- starts
# from a computed answer rather than an absent one.
playthrough_trust_refresh || true

# THE SUMMARY'S STATUS IS THE DIRECT RUN'S STATUS. `bash
# playthrough/tooling/env.sh` exists to PRINT the contract, so a summary that
# could not be written is a failed run and has to say so with its exit code.
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

# Leave no scratch names behind in the caller's shell. Only the exported
# PLAYTHROUGH_* set, the six environment variables and the helper functions are
# part of this file's contract.
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
