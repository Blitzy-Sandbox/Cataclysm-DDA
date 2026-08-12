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
# playthrough_redact TEXT
#   Strip host locations out of one diagnostic line.
#
#   EVERY LINE THESE HELPERS PRINT GOES THROUGH THIS.  Diagnostics are
#   retained: they are captured into log files, quoted into reports and
#   read by people who have no business knowing where somebody else's
#   clone lives or how this host lays out its runtime state.  Doing the
#   redaction here rather than at each of the fifty-odd call sites is
#   deliberate -- it cannot be forgotten at a new one, and it cannot
#   change the argument structure of an existing one.
#
#   Two substitutions, both purely textual:
#     * the checkout's absolute path becomes its repository-relative
#       form, so /long/host/path/playthrough/manifest.jsonl reads as
#       playthrough/manifest.jsonl -- which is what a reader would type;
#     * the runtime scratch root becomes "<runtime>", keeping the file
#       name that matters while dropping the location that does not.
#
#   It is a no-op until those variables exist, which is correct: the
#   handful of lines printed before the layout is derived cannot contain
#   a path derived from it.  playthrough_rel is the same rule applied to
#   a single path on purpose, and manifest.relative_to_repo() is the
#   Python half.
# The ceiling on a value that becomes one line of the record.
#
# Generous beside anything real -- CDDA world names are short, and the
# survivor name this pipeline derives is bounded at 120 by make_srt.py --
# and small enough that a value past it is evidently not a name.  It is
# declared here rather than beside the other limits because
# playthrough_assert_record_token below is the first thing in this file
# that needs it.
PLAYTHROUGH_MAX_RECORD_TOKEN=128

# playthrough_has_control TEXT
#   True when TEXT contains a C0 control, DEL, or a C1 control.
#
#   THE PATTERNS ARE BYTES, DELIBERATELY.  The first arm covers C0
#   (0x01-0x1F, so tab, newline, carriage return and ESC) and DEL; the
#   second covers the C1 block, which in UTF-8 is 0xC2 followed by
#   0x80-0x9F -- and C1 matters because 0x9B is a single-byte CSI that
#   some terminals honour exactly like ESC-[.
#
#   Legitimate non-ASCII is NOT refused: a world or survivor name may be
#   spelled with accents or in another script, and refusing that would be
#   parochial rather than safe.  Verified on this host, in LC_ALL=C, in
#   C.UTF-8, and with no LC_ALL set at all -- identical every time:
#   newline, CR, tab, ESC, DEL, BEL, U+0085 and U+009B are all detected,
#   while 'Sunnysidé' and Cyrillic text are clean.  The byte ranges make
#   the answer independent of the caller's locale, which a
#   [[:cntrl:]] class would not be.
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
#
#   Used by playthrough_redact, so it applies to EVERY diagnostic this
#   pipeline writes.  A review found world names reaching log and
#   KEY=value output with no rejection of C0/C1/newline: a name carrying
#   a newline forges a whole extra log line, and one carrying ESC-[ can
#   repaint the terminal of whoever is reading the run.  Escaping at the
#   single point every message passes through is what makes that true of
#   all inputs rather than of the ones somebody remembered.
playthrough_escape_controls() {
    # BYTES, DETERMINISTICALLY, whatever the caller's locale is.  This
    # walked the value one CHARACTER at a time, and "character" is a
    # locale question: in a UTF-8 locale ${rest:0:1} takes the whole
    # two-byte C1 sequence, and in the C locale it takes one byte of it.
    # Measured, and the C-locale outcome was the bad one -- U+009B came
    # back SILENTLY DELETED rather than escaped, which is safe but throws
    # away the evidence that anything was there.  A local LC_ALL makes the
    # walk bytewise everywhere, so the output is a property of the input
    # rather than of the environment that happened to call it.
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
                # A C1 control is 0xC2 followed by 0x80-0x9F.  Both bytes
                # are consumed together and reported as the CODEPOINT,
                # which is the second byte's value -- so U+009B reads
                # <9B> rather than as two meaningless halves.
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
#
#   THE GRAMMAR: non-empty, no longer than
#   PLAYTHROUGH_MAX_RECORD_TOKEN, and free of C0, DEL and C1 controls.
#   Applied to values that are chosen OUTSIDE this pipeline and then
#   published inside it -- a world name is a directory name any local
#   account can create under the save tree, and it is emitted as
#   PLAYTHROUGH_SAVE_WORLD, which later stages parse as KEY=value.  A
#   newline in it appends a line of that record that nothing wrote.
#
#   The refusal reports the value ESCAPED, because a diagnostic that
#   printed the offending bytes raw would perform the injection it is
#   complaining about.
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

# ---------------------------------------------------------------------
# THE TRUSTED UTILITY BOOTSTRAP
#
# A security check is worth no more than the program that performs it.
# Every ownership, mode and containment check below is a call to `stat`,
# `readlink` or `chmod`, and each of those used to be resolved through
# the INHERITED PATH -- the one thing in this environment that an
# attacker who can already write a directory on it also controls.  A
# planted `stat` that prints this uid for every path would make every
# check below answer "yours", and the pipeline would then write its
# Xauthority cookie, its locks, its captures and its rendered film into a
# directory somebody else owns while reporting the state as trusted.
#
# So the utilities are resolved from a FIXED list of system directories,
# never from PATH, and the resolved `stat` is then used to verify itself
# and its siblings: each must be a regular executable owned by root or by
# this user and writable by neither group nor world.  The limit of that
# chain is stated plainly rather than glossed: if /usr/bin/stat is itself
# replaced by something with root's cooperation, nothing in user space
# can tell.  What this closes is the case that does not need root -- a
# writable directory earlier on PATH.
#
# THE BOOTSTRAP RUNS AT SOURCE TIME, before the first playthrough_secure_dir
# call, because that call is one of the things it protects.
# ---------------------------------------------------------------------

# Where a security-critical utility may come from.  System directories
# only, in the order a sane host orders them; PATH is deliberately not
# consulted, and neither is anything under /usr/local, /opt or a home
# directory, because those are the paths a non-root account can more
# often write.
PLAYTHROUGH_TRUSTED_UTIL_DIRS="/usr/bin /bin /usr/sbin /sbin"

# The utilities the checks below cannot be PERFORMED without.  All three
# are coreutils, which every platform this pipeline targets ships.
PLAYTHROUGH_TRUSTED_UTILS="stat readlink chmod"

# playthrough_trust_unverifiable REASON
#   Record that a security check could not be PERFORMED at all.
#
#   THIS IS NOT A WARNING CHANNEL.  It is the third input to the trust
#   state, beside the named bypasses and the platform waiver, and it
#   exists because "the check failed" and "the check did not run" used to
#   be reported the same way -- as a warning next to a return code of
#   zero.  An inability to verify is not a verification, so it is
#   recorded here, it holds PLAYTHROUGH_TRUST_STATE at "diagnostic", and
#   playthrough_assert_trusted then refuses a launch or a production
#   capture that would otherwise proceed as trusted.
#
#   The caller ALSO fails closed.  Recording is not an alternative to
#   refusing; it is what makes the refusal visible to the stages that
#   never saw the call.
playthrough_trust_unverifiable() {
    local reason="${1-an unnamed security check could not be run}"
    local existing="${PLAYTHROUGH_TRUST_UNVERIFIED-}"
    case "${existing}" in
        *"${reason}"*) ;;
        '') existing="${reason}" ;;
        *) existing="${existing}; ${reason}" ;;
    esac
    export PLAYTHROUGH_TRUST_UNVERIFIED="${existing}"
    # This can fire at source time, before the trust helpers further
    # down the file exist -- the very first playthrough_secure_dir call
    # is one of the things the bootstrap protects.  So the state is set
    # here directly in that window, which matters because a source that
    # ABORTS never reaches the refresh at the end of the file, and the
    # answer a consumer would then read out of the environment has to be
    # "diagnostic" rather than empty.
    if command -v playthrough_trust_refresh >/dev/null 2>&1; then
        playthrough_trust_refresh >/dev/null 2>&1 || true
    else
        export PLAYTHROUGH_TRUST_STATE="diagnostic"
    fi
    return 0
}

# playthrough_trusted_util NAME
#   Print the absolute path of NAME inside the trusted directories, or
#   return 1.  The name is checked against a closed vocabulary -- plain
#   lower-case letters -- so nothing resembling a path or a shell
#   metacharacter can be appended to a trusted directory here.
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
#   Resolve every name in PLAYTHROUGH_TRUSTED_UTILS, verify the set with
#   the resolved `stat`, and export PLAYTHROUGH_UTIL_<NAME> plus
#   PLAYTHROUGH_UTILITY_TRUST ("trusted" or "unresolved").
#
#   PLAYTHROUGH_UTIL_<NAME> is a computed namespace -- the loop below
#   builds each name from an entry of PLAYTHROUGH_TRUSTED_UTILS -- so the
#   verdict over the whole set is deliberately NOT called
#   PLAYTHROUGH_UTIL_STATE.  A name of that shape would collide with a
#   trusted utility called `state`, and it also reads as a typo of
#   PLAYTHROUGH_UTIL_STAT, which is the one variable in the namespace
#   every ownership check depends on.
#
#   Verification is deliberately narrow: owner root or this user, and
#   neither group- nor world-writable, for the utility itself.  The
#   directories above it are checked by playthrough_verify_executable for
#   the pipeline's own tools; doing the same walk for three coreutils
#   binaries at source time would cost a dozen processes on every stage
#   for an answer that /usr/bin being group-writable would already have
#   made hopeless.
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
#
#   Every secure_* helper calls this first, and none of them has a
#   "could not check, carrying on" branch any more: an unperformed check
#   returning success is worse than no check at all, because it produces
#   a positive answer nobody can distinguish from a verified one.
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
#   What is confirmed is the PERMISSION BITS, not the whole `stat %a`
#   string: a directory created inside a set-group-ID parent inherits
#   setgid, GNU chmod preserves that bit on directories, and 2700 is
#   exactly as private as 700.  session.py's _secure_dir() applies the
#   same rule (`st_mode & 0o077`), and the two must not drift apart --
#   see the comment beside the comparison for what happened when they
#   did.
#
#   LABEL is what the diagnostics call the directory; it defaults to the
#   path itself.  This is the ONLY way anything in this tree brings a
#   scratch directory into existence.
#
#   `stat` IS THE CHECK, and it is called through the trusted bootstrap
#   above rather than through PATH -- so a PATH stripped down to bash
#   itself no longer costs this function its verification, which is what
#   used to make an inability to verify look unavoidable.  If the
#   bootstrap could not resolve it, this REFUSES: it does not chmod
#   hopefully and return success, because an unperformed ownership check
#   reporting success is indistinguishable from a verified one, and the
#   directory it blesses is where the Xauthority cookie, the step lock
#   and the capture staging live.
# ---------------------------------------------------------------------
# THE INHERITED ENVIRONMENT IS NOT TRUSTED EITHER
#
# Every external command in this tree is resolved by absolute path and
# verified -- owner, writability, and the same for every directory above
# it -- so that a tool another account can replace cannot decide a
# reading in the film.  A security review pointed out the hole beside it:
# the ENVIRONMENT those verified binaries inherit is a second way to
# choose what code they run, and nothing looked at it.
#
#   * `BASH_ENV` names a file bash SOURCES at the start of every
#     non-interactive shell.  Every stage in this tree is a
#     non-interactive bash script, so one variable runs a caller's file
#     inside all nine of them, before their first line.
#   * `LD_PRELOAD` and `LD_AUDIT` load a caller's shared object into
#     every dynamically linked process -- the engine, ImageMagick,
#     ffmpeg, tesseract, git -- and override any symbol in it.
#     `LD_LIBRARY_PATH` does the same thing one step less directly.
#   * `PYTHONSTARTUP` and `PYTHONEXECUTABLE` reach the interpreter;
#     `PYTHONPATH` and `PYTHONHOME` decide which modules the pipeline's
#     own imports resolve to.
#   * `GIT_CONFIG_COUNT` with `GIT_CONFIG_KEY_n`/`GIT_CONFIG_VALUE_n`
#     injects arbitrary configuration -- including `core.hooksPath`,
#     `core.fsmonitor` and a credential helper -- into every git call,
#     outranking the file this pipeline contains hooks with.
#     `GIT_DIR`, `GIT_WORK_TREE`, `GIT_INDEX_FILE`,
#     `GIT_OBJECT_DIRECTORY`, `GIT_ALTERNATE_OBJECT_DIRECTORIES` and
#     `GIT_NAMESPACE` redirect where the evidence is read from and
#     written to; `GIT_SSH`, `GIT_SSH_COMMAND`, `GIT_EXTERNAL_DIFF`,
#     `GIT_PROXY_COMMAND` and `GIT_ASKPASS` name programs git executes.
#   * `MAGICK_*` name ImageMagick's coder and filter MODULE paths --
#     shared objects it loads to decode a PNG -- and `FONTCONFIG_FILE`
#     redirects font resolution, which is what the attested Terminus
#     digest exists to pin.
#
# THEY ARE REFUSED, NOT UNSET, and the distinction is deliberate.  None
# of them has a legitimate reason to be set for this pipeline, so their
# presence is either an attack or a misconfiguration serious enough that
# proceeding quietly would be the wrong service: a run that silently
# discarded a caller's `PYTHONPATH` would be doing something other than
# what the caller asked, and one that honoured it would be running the
# caller's code.  Saying so and stopping is the only honest third option,
# and the fix is one `env -u NAME` away.
#
# THERE IS NO WAIVER for this, unlike the platform and path-ancestry
# gates, and that is because it is not a property of the host: nothing
# about any machine requires these to be set, so there is no environment
# in which the refusal is the wrong answer.
#
# WHAT IS DELIBERATELY LEFT ALONE, because refusing it would break a
# legitimate mechanism:
#
#   * `GIT_AUTHOR_*` and `GIT_COMMITTER_*` are how the platform supplies
#     the committer identity -- see commit_artifacts.sh, which asserts an
#     identity and never writes git configuration.
#   * `GIT_CONFIG_GLOBAL`, `GIT_CONFIG_SYSTEM` and `GIT_CONFIG_NOSYSTEM`
#     NARROW git's configuration rather than adding to it, and they are
#     how this tree's own suites isolate a sandbox repository from the
#     host's configuration.  They are VERIFIED instead of refused: a
#     nominated configuration file must be a regular file this user owns
#     and must not be writable by anybody else, which closes the
#     injection path while leaving the isolation intact.
#   * `GIT_TERMINAL_PROMPT`, and env.sh's own `PYTHON*` exports.
#
# `PYTHONNOUSERSITE=1` is exported below rather than adding `-s` to
# fifteen call sites: it is exactly equivalent, it cannot be forgotten at
# a new one, and it keeps the per-user site directory -- which is
# writable by this account and by nothing else the pipeline verified --
# out of every interpreter this run starts.  `-P`/`PYTHONSAFEPATH` is
# deliberately NOT set: it would drop the script's own directory from
# sys.path and the pipeline's modules import each other by name.
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
#   Returns 0 when the environment is acceptable, 1 when it is refused.
#
#   Called ONCE, at source time, before anything in this file starts a
#   child process -- which is the only placement that means anything: a
#   check that ran after the first `stat` would be reporting on an
#   environment that had already been used.
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
#
#   THE SPECIAL-BITS DIGIT IS NOT PART OF THE ANSWER, and that is the
#   whole reason this exists as a helper rather than as a bare
#   `stat -c %a`.  A directory created inside a set-group-ID parent
#   inherits setgid, and /tmp is mode 2777 on this class of host, so
#   `stat %a` answers "2700" for a directory that is private by every
#   definition that matters.  Callers comparing against 700, or masking
#   with 8#077, need the access bits and nothing else.
#
#   Symlinks are FOLLOWED (-L), because every caller is asking about the
#   thing it is going to read or write, not about the link naming it;
#   callers that must refuse a link do so separately and before this.
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
#   callers that must not proceed on an unknown mode ask
#   playthrough_permission_bits directly and refuse on empty, because
#   "unreadable" and "safe" are different facts and only one of them is
#   worth continuing on.
playthrough_is_group_or_world_writable() {
    local bits
    bits="$(playthrough_permission_bits "${1-}")" || return 1
    [ $(( 8#${bits} & 8#022 )) -ne 0 ]
}

# playthrough_untrusted_ancestor PATH
#   Print the first directory AT OR ABOVE PATH that is group- or
#   world-writable WITHOUT the sticky bit, walking all the way to '/'.
#   Prints nothing and returns 1 when every ancestor is safe.
#
#   WHY THIS IS A SEPARATE, WALK-TO-THE-ROOT MEASUREMENT.  A security
#   review found that this tree checked the mode of each directory it
#   used and of each ancestor BELOW its own verified anchor, and stopped
#   there -- so on a host whose /tmp is mode 2777 and NOT sticky
#   (measured on the provisioning host; a normal /tmp is 1777) the fact
#   that the anchor's own NAME could be renamed out from under it by any
#   local account was never measured and never reported.  That is the
#   gap this closes: not the mode of the thing, the mode of the road to
#   it.
#
#   THE STICKY BIT IS THE WHOLE DISTINCTION, and it is why a 1777 /tmp is
#   not a finding while a 2777 one is.  In a world-writable directory
#   WITHOUT the sticky bit, any account with write permission may rename
#   or unlink ANY entry regardless of who owns it; with the sticky bit
#   set, only the entry's owner (or the directory's, or root) may.  So a
#   private 0700 subtree under a 1777 /tmp really is private, and the
#   same subtree under a 2777 /tmp can have its top component replaced
#   between one check and the next use.
#
#   A REPORTER, NOT A JUDGE.  It returns the offending path and leaves
#   "fatal, degrading or merely noted" to the caller, because the answer
#   genuinely differs: the pipeline can MOVE its own runtime anchor, and
#   cannot move the checkout it was given.
#   THE WHOLE `stat %a` STRING IS READ HERE, not
#   playthrough_permission_bits, and that is load-bearing: that helper
#   DROPS the special-bits digit -- correctly, for callers comparing
#   against 700 on a setgid-inheriting directory -- and the sticky bit
#   lives in exactly that digit.  Reading through it would strip the one
#   bit this function turns on, and every world-writable ancestor would
#   be reported as unsafe including a conventional 1777 /tmp.  Measured:
#   the first version of this function did that and a sticky-bit test
#   caught it.
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
    # The mode BEFORE the chmod, so that a repair can be announced.  A
    # directory found at the mode it should already have is the normal
    # case and says nothing -- sourcing this file has to stay silent --
    # but one found wider is a different matter: something else opened
    # the pipeline's private runtime state to other accounts, and the
    # repair is the only moment anyone would ever learn that happened.
    # Fixing it quietly would leave the operator believing it had always
    # been 0700.
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
    # digit is not part of it.  Two facts make the whole-string compare
    # wrong rather than merely strict:
    #
    #   * a directory created inside a set-group-ID parent INHERITS the
    #     setgid bit, and /tmp is mode 2777 on some hosts -- including
    #     the one this pipeline was provisioned on;
    #   * GNU chmod DELIBERATELY preserves a directory's set-user-ID and
    #     set-group-ID bits when it is given a three-digit octal mode,
    #     so `chmod 700` on such a directory leaves `stat %a` reading
    #     2700 and no number of retries changes that.
    #
    # So a directory whose access bits are exactly 0700 -- private, by
    # every definition that matters here -- was being refused, and the
    # refusal was unconditional: sourcing this file died, and with it
    # every stage that sources it.  session.py's own _secure_dir()
    # tests `st_mode & 0o077` and therefore always accepted the same
    # directory, so the two halves of one contract disagreed and a host
    # with a setgid temporary directory could run one and not the
    # other.  They agree now: no group or other bit, and the setgid bit
    # is left to the filesystem that put it there.
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
    # The parent is derived with bash's own parameter expansion rather
    # than by calling `dirname`: this value is handed straight to
    # playthrough_secure_dir, so a substituted `dirname` on the inherited
    # PATH could point the mode-0700 adoption at a directory of its own
    # choosing.  Nothing outside the shell is involved in computing it.
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
    # THE CHECK'S OWN TOOLS FIRST.  `stat` and `readlink` are what this
    # function is made of, so a run that cannot call them has not
    # verified anything -- and this used to answer that case with
    # `return 0`, which told every caller the executable had been
    # cleared for third-party ownership when nothing had been read at
    # all.  The bootstrap resolves both from fixed system directories
    # rather than from PATH, so a thin PATH no longer reaches this
    # branch; if they are genuinely absent the answer is a refusal.
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
#   Refuse a path that does not resolve inside ROOT.  readlink -m
#   resolves every existing component, so neither a `..` segment nor a
#   symlink can smuggle a destination past this.
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
#
#   AN XAUTHORITY IS A CREDENTIAL, and until a security review said so
#   the only test applied to an INHERITED one was `-f`: it existed.  That
#   is not enough in three separate directions, and each of them is a
#   real attack rather than a tidiness argument:
#
#     * a SYMLINK at the nominated path makes `xauth add` write the
#       cookie wherever the link points -- and xauth writes through the
#       link, so a caller-supplied XAUTHORITY was a write primitive into
#       any file this user can write;
#     * ANOTHER ACCOUNT'S FILE, read as ours, hands that account the
#       display: it chose the cookie, so it can connect to the server
#       this pipeline is photographing, read the screen and inject
#       keystrokes -- which breaks the one-frame-per-keystroke invariant
#       and leaves no trace in any artifact;
#     * GROUP OR WORLD ACCESS on the file, or on any directory above it,
#       is the same exposure by a slower route: whoever can read the
#       cookie is authenticated, and whoever can write the directory can
#       replace the file between this check and the next connection.
#
#   So the file must be a regular file, reached through no symlink at any
#   component, owned by this user, carrying no group or world bits at
#   all, and every directory above it must be free of group and world
#   write access (the sticky bit excuses /tmp-shaped ancestors, which is
#   how a private 0700 directory under a 1777 /tmp is still private).
#
#   A PREDICATE with a reason: it reports each failure on stderr and
#   returns non-zero, leaving "fatal or not" to the caller, because the
#   answer differs between an inherited file (refuse the run) and our own
#   (create it correctly instead).
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
    # THE WALK STOPS AT THE VERIFIED RUNTIME ROOT for its REFUSAL, and
    # goes past it for its REPORT.  Both halves matter and a review found
    # the second one missing.
    #
    # Why the refusal stops there: this host's /tmp is mode 2777 --
    # world-writable and NOT sticky (measured) -- so a refusal that ran
    # to '/' would refuse every path under it, including this pipeline's
    # own private tree, and the anchor has separately been proved to be a
    # real, non-symlink, owner-only 0700 directory owned by this user.
    # An ancestor BELOW that anchor is a genuine local defect and stays
    # fatal.
    #
    # Why the report goes past it: "the anchor is private" and "the road
    # to the anchor cannot be re-paved by another account" are DIFFERENT
    # facts, and the second one used to be neither measured nor said. It
    # is now measured once, when the anchor is chosen, and carried in
    # PLAYTHROUGH_RUNTIME_UNTRUSTED_ANCESTOR -- which also degrades the
    # trust state, so nothing produced through such a road is reported as
    # produced in a trusted environment.  This function names it beside
    # the credential it is about, because a reader looking at the X
    # cookie should not have to go and find that out.
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
#   resolved, WITHOUT requiring it to exist.  Empty input and an
#   unresolvable path are refusals rather than empty output, so a caller
#   cannot mistake "nothing to say" for "the root of the filesystem".
#
#   This is the non-fatal counterpart of playthrough_assert_inside's
#   resolution step: containment has to be decided before a directory is
#   created, so `readlink -m` is the right mode -- it resolves what
#   exists and treats the rest as literal, which is exactly the question
#   "where WOULD this land".
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
#   True when PATH is BASE itself or lies beneath it, both canonicalised
#   first.  A PREDICATE, silent on both answers: the callers that must
#   refuse print their own reason, which is always more specific than
#   anything a shared helper could say.
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
# THE ENVIRONMENT IS SANITISED FIRST, before this file resolves a path,
# starts a child or reads a file.  Placement is the whole of the control:
# a check that ran later would be reporting on an environment that had
# already been used, and `BASH_ENV` in particular has run its file before
# any line of this one executes -- which is why the refusal names it
# rather than pretending to have prevented it.  See THE INHERITED
# ENVIRONMENT IS NOT TRUSTED EITHER, above.
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
# AND ITS ANCESTRY IS NOW PART OF THE CHOICE, not just its own inode.
#
# A security review measured what the paragraph above already suspected
# and stopped short of acting on: /tmp on the provisioning host is mode
# 2777 -- world-writable and NOT sticky -- so `/tmp/xdg` is a private
# 0700 directory reached through a road any local account may re-pave.
# Verifying the destination cannot fix the road.
#
# So the anchor is CHOSEN from an ordered list of candidates, and the
# first one whose whole ancestry is free of group- or world-writable
# non-sticky directories wins:
#
#   1. $PLAYTHROUGH_XDG_ANCHOR, when a caller nominates one.  It is held
#      to exactly the same verification as the defaults -- the control is
#      that the anchor is proved, not that it is hard-coded -- and it is
#      how an operator on an unconventional host asks for a better
#      address without editing this file.
#   2. /tmp/xdg<suffix>, the historical default, WHEN IT ALREADY EXISTS.
#      Continuity outranks a better address here, and not as a
#      concession: this directory holds live state -- the X authority
#      cookie, the pid files of a running server, the lock files, an
#      in-flight step journal -- and silently moving the anchor out from
#      under a running session would orphan every one of them and turn a
#      display this checkout owns into a foreign one.  An untrusted
#      ancestry on this branch is REPORTED and it DEGRADES THE TRUST
#      STATE, so nothing produced through such a road can be reported as
#      produced in a trusted environment, and
#      playthrough_assert_trusted refuses a launch or a production
#      capture on it.
#   3. /run/playthrough-<uid><suffix>, under a root-owned /run, which is
#      the "root-controlled parent" the finding asks for.  It carries the
#      clone-index suffix for the same reason the legacy path does: two
#      clones must not share one runtime root, and /run/user/<uid> --
#      the other address that would qualify -- is per USER and cannot
#      carry that suffix without ceasing to be the thing it is.
#   4. /tmp/xdg<suffix>, created, as the last resort on a host with no
#      /run at all.  Reported and trust-degrading, like branch 2.
#
# On a host with a normal 1777 /tmp -- which includes the supported
# container -- branches 2 and 4 are trusted anyway, and the sticky bit is
# why: see playthrough_untrusted_ancestor for the difference the bit
# makes.  The ordering therefore costs a conventional host nothing and
# earns an unconventional one a real ancestor.
_playthrough_legacy_anchor="/tmp/xdg${_playthrough_suffix}"
_playthrough_runtime_dir=""
_playthrough_unsafe_ancestor=""
if [ -n "${PLAYTHROUGH_XDG_ANCHOR-}" ]; then
    # A NOMINATION IS FATAL WHEN IT FAILS.  Falling back to a default
    # after a caller has asked for a specific anchor would silently put
    # the X cookie, the locks and the withdrawn frames somewhere the
    # caller did not choose -- which is the whole class of surprise a
    # nomination exists to avoid.
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
# THE ANCESTRY IS EXPORTED AS A FACT, so every stage and the acceptance
# gate read the same answer instead of each re-deriving it.  Empty means
# every directory from the anchor to '/' is free of group- or
# world-writable non-sticky components.
export PLAYTHROUGH_RUNTIME_UNTRUSTED_ANCESTOR=\
"${_playthrough_unsafe_ancestor-}"
unset _playthrough_legacy_anchor _playthrough_unsafe_ancestor

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
#
# TWO CONTAINMENT RULES BOUND THAT NOMINATION, and both answer a real
# finding rather than a hypothetical.
#
#   1. IT MAY NOT BE INSIDE THE CHECKOUT.  The terminal
#      `!/playthrough/**` negation in .gitignore re-includes everything
#      under playthrough/, so a runtime root placed there turns the X
#      cookie, the pid files, the lock files and the withdrawn frames
#      into stageable, committable paths -- a credential in a commit,
#      and diagnostics in an evidence tree.  Anywhere in the repository
#      is refused, not just playthrough/: a root at the repository root
#      would be picked up by `git status` and by the hygiene checks, and
#      a root ABOVE the repository that CONTAINS it is refused for the
#      same reason in the other direction.
#   2. IT MUST LIE BENEATH THE VERIFIED XDG RUNTIME ROOT.  That root is
#      the one directory this file has already proved is a real,
#      non-symlink, owner-only 0700 directory owned by this user, so
#      constraining the nomination beneath it makes every runtime
#      artifact inherit a verified private ancestor instead of only
#      being verified at its own inode.  The cost is deliberate: a
#      nominated root under an unverified ancestor is exactly the
#      redirect this block exists to prevent, and a caller who needs the
#      tree somewhere else moves XDG_RUNTIME_DIR's own location (the
#      CLONE_INDEX suffix above) rather than escaping the check.
#
# Neither rule is a trust bypass with an escape hatch, because there is
# no legitimate run that needs one: the default already satisfies both.
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

# PYTHONNOUSERSITE=1 IS `-s` FOR EVERY INTERPRETER THIS RUN STARTS, and
# exporting it is why `-s` does not have to be remembered at fifteen call
# sites.  It keeps ~/.local/lib/pythonX.Y/site-packages out of sys.path,
# which matters because that directory is writable by this account and is
# not one of the paths the executable verification covers: a module
# planted there would shadow one of the six pinned, hash-locked
# distributions and decide the readings in the film.
#
# `PYTHONSAFEPATH` (the `-P` flag) is deliberately NOT set: it would drop
# the script's own directory from sys.path, and this pipeline's modules
# import each other by name -- make_srt imports timeline, session imports
# manifest.  `-E`'s effect is achieved instead by
# playthrough_sanitize_environment refusing the PYTHON* variables
# outright, which is stronger: -E would silently ignore a poisoned
# PYTHONPATH where the refusal says it was there.
export PYTHONNOUSERSITE=1

# ---------------------------------------------------------------------
# Artifact layout -- one authoritative definition for every sibling
#
# Absolute paths, so a consumer is correct even if it is invoked from
# elsewhere; plus the two repository-root-relative forms that are
# passed to the game on the command line, which MUST stay relative
# for the reasons given under WORKING DIRECTORY above.
# ---------------------------------------------------------------------
export PLAYTHROUGH_REPO_ROOT="${_playthrough_repo_root}"

# playthrough_rel PATH
#   PATH spelled relative to the repository root.  THE ONLY FORM A
#   MACHINE SUMMARY OR A DIAGNOSTIC REPORTS.
#
#   An absolute path discloses where this checkout lives on the host,
#   and these lines are kept in logs, quoted into reports and read by
#   people who have no business knowing that.  Every artifact this
#   pipeline touches is inside the checkout, so the relative form is
#   complete as well as smaller: it is what a reader would type.
#
#   A path genuinely OUTSIDE the checkout is reduced to its basename
#   behind a marker rather than printed, and rather than spelled as a
#   traversal -- "../.." still discloses depth, and an outside path is a
#   fault to notice, not a location to publish.  manifest.py's
#   relative_to_repo() is the Python half of exactly this rule.
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

# The AMENDMENT LEDGER, and why a correction lives outside the record it
# corrects.
#
# The manifest is append-only, which means a row that was written is the
# row that stays: there is no editor, no read-modify-write, no "w" mode
# anywhere in manifest.py.  That rule has a cost -- a commentary sentence
# that turns out to overstate what its own capture shows cannot be fixed
# in place -- and paying that cost in the wrong direction is what a
# security review found here: rows HAD been rewritten after capture, and
# every derivative was regenerated to agree with the altered history, so
# the record and the film were perfectly consistent with each other and
# both disagreed with what was captured.
#
# So a correction is a NEW, SEPARATE, APPEND-ONLY record that names the
# sha256 of the exact manifest line it amends.  A reader sees the
# original sentence, the corrected sentence, the reason, and the digest
# proving which line was meant; a consumer applies an amendment only when
# that digest still matches, and refuses to resolve the record at all
# when it does not.  Nothing is erased, and a divergence cannot hide.
export PLAYTHROUGH_AMENDMENTS="${PLAYTHROUGH_DIR}/amendments.jsonl"

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
# for the same frame, so one logical record has one writer.
#
# A FRAME CAPTURED TWICE HAS TWO ROWS, AND THEY MUST AGREE.  This used to
# be a last-occurrence rule, borrowed from the engine's own handling of
# duplicated option entries, and a security review named both things
# wrong with it here.  Two rows that DISAGREED about the date still
# decided a day, on nothing better than which was written later.  And a
# later row whose date was `null` -- the ordinary shape of an unreadable
# reading -- silently ERASED a date that had been read successfully.
# timeline.py now requires unanimity: readings that agree corroborate
# each other, a `null` is an absence of evidence rather than
# counter-evidence, and a genuine disagreement makes that frame's date
# UNOBSERVED and is reported.  Each row also names the sha256 of the
# frame it was read from, so a reading cannot be attributed to a
# different photograph that later took the same index.
#
# THAT WAS TRUE OF THE DATE AUDIT AND NOT OF THIS FILE, WHICH IS WORTH
# STATING BECAUSE THIS PARAGRAPH ASSERTED IT OF BOTH.  A code review
# found timeline.load_observations() still taking the LAST row for a
# frame, with no unanimity, no digest check and no schema validation,
# while build_timeline PREFERRED this record over the hardened audit --
# so one stale telemetry row could override unanimous, digest-bound
# audit evidence and change the film's pacing.  Both readers now apply
# the same rule, and the two records are held to unanimity against EACH
# OTHER as well: neither is preferred, because there is no rule by which
# one file's reading of the same photograph beats the other's, and a
# contradiction between them leaves that frame's date unobserved.  Rows
# written before the attestation ledger existed carry no `frame_sha256`
# -- every row of the committed record is in that state -- and are used
# with the fact reported once, never presented as checked.
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

# The CAPTURE ATTESTATION LEDGER.  One append-only row per published
# frame, naming its sha256 and its byte length.
#
# Until this existed, nothing in the pipeline ever recorded what a
# capture's BYTES were.  Every downstream check was structural -- the
# frame count equals the row count, the file exists, it is 1920x1080, it
# is not blank -- and a security review named the consequence exactly: a
# same-sized, non-blank, correctly-named replacement PNG dropped into
# playthrough/frames/ passed the whole chain, and the recovery path
# actively trusted the pixels it found on disk plus an mtime any writer
# can set.
#
# capture.sh hashes the file immediately after the atomic publication
# that makes it visible and fails the capture if it cannot; session.py
# re-hashes the published bytes before a manifest row exists and appends
# the attestation for the frame it just took; timeline.py verifies the
# whole ordered set before it times anything, and the transition
# composer, the encoder and the caption generator inherit that check
# through assert_timeline_document().
#
# It lives under build/ because it is derived evidence about the frames
# rather than a narrative artifact, and it is append-only for the same
# reason the manifest is: an attestation that can be rewritten attests
# nothing.
export PLAYTHROUGH_FRAME_DIGESTS="${PLAYTHROUGH_BUILD_DIR}/\
frame_digests.jsonl"

# WHAT THE OPERATOR SAW BETWEEN THE KEYS, and it is named here because
# the acceptance gate reads it.  session.py appends one row per frame
# that was looked at, and a review found the consequence of nothing else
# reading the file: frame 298 had been read twice with neither row saying
# it replaced the other, and frame 307 -- the last capture -- had not
# been read at all.  Both now fail the gate.
export PLAYTHROUGH_ACKNOWLEDGMENTS="${PLAYTHROUGH_BUILD_DIR}/\
acknowledgments.jsonl"

# THE ONE ARTIFACT THAT VOUCHES FOR THE OTHERS FROM OUTSIDE THEMSELVES.
#
# Every ledger above sits in the same tree as the evidence it describes,
# under the same permissions, so none of them can answer "was this
# changed after the fact" -- the answer would have to come from the file
# being asked about.  This is a hash-chained, append-only seal: each row
# carries an artifact's sha256, GIT'S OWN NAME for the same bytes
# (`git hash-object` re-derives it, computed by code nobody here wrote),
# and the previous row's chain hash.  commit_artifacts.sh publishes the
# chain head as a `Playthrough-Evidence-Anchor:` trailer at each
# checkpoint, and a commit object's name is a hash of its own content --
# so rewriting an artifact means rewriting this ledger AND rewriting
# published history.
#
# Sealing build/frame_digests.jsonl seals all 307 captures transitively,
# which is why the sealed set is short enough to read: a substituted
# frame breaks its digest row, repairing that row breaks the seal, and
# repairing the seal breaks the chain and the committed trailer.
export PLAYTHROUGH_EVIDENCE_ANCHOR="${PLAYTHROUGH_BUILD_DIR}/\
evidence_anchor.jsonl"
export PLAYTHROUGH_MOVIE="${PLAYTHROUGH_DIR}/cata-play.mp4"
export PLAYTHROUGH_MOVIE_CC="${PLAYTHROUGH_DIR}/cata-play-cc.mp4"
export PLAYTHROUGH_TRANSCRIPT_MD="${PLAYTHROUGH_DIR}/transcript.md"
export PLAYTHROUGH_TRANSCRIPT_SRT="${PLAYTHROUGH_DIR}/transcript.srt"
export PLAYTHROUGH_DOSSIER="${PLAYTHROUGH_DIR}/dossier.md"
export PLAYTHROUGH_TECH_NOTES="${PLAYTHROUGH_DIR}/TECHNICAL_NOTES.md"
# The mandated final report: exactly three sections, in the order the
# plan fixes them -- A) Screen Recording and Animation, B) Character
# Creation, C) Playing the Game.  Named here rather than in the
# committer so that the one list of narrative paths a checkpoint stages
# stays derived from this file, which is where every other artifact path
# in this pipeline is declared.
export PLAYTHROUGH_REPORT="${PLAYTHROUGH_DIR}/REPORT.md"
# The COMMITTED acceptance report, and the scratch file it is published
# FROM.  Two paths for one document, and the split is the whole point.
#
# verify_artifacts.sh used to write playthrough/acceptance-report.txt
# itself, on a passing run, and delete it on a failing one -- writes
# inside the tree it was measuring, taken after the very checks that
# assert that tree is clean and fully committed.  A review measured the
# consequence: a full-phase run after the final checkpoint left the tree
# dirty in the one file it had just certified as committed.
#
# So the measurement now writes only where its caller names with
# --report-to, which must be outside the checkout, and PUBLISHING is a
# separate deliberate act: the attestation checkpoint copies the scratch
# report to the committed path and commits it in the same breath, so the
# tree is dirtied and cleaned inside one step that can be refused as a
# whole.  The scratch path lives under the runtime root, which env.sh
# already keeps outside the working tree and refuses to nominate inside
# it.
export PLAYTHROUGH_ACCEPTANCE_REPORT="${PLAYTHROUGH_DIR}/\
acceptance-report.txt"
export PLAYTHROUGH_ACCEPTANCE_SCRATCH="${PLAYTHROUGH_RUNTIME_DIR}/\
acceptance-report.txt"
export PLAYTHROUGH_REQUIREMENTS="${PLAYTHROUGH_TOOLING_DIR}/requirements.txt"
# The install contract beside the declaration.  requirements.txt says
# WHICH six libraries; the lock says which exact wheel of each, by
# sha256.  Both are needed to answer "is the environment the one this
# pipeline was reviewed against", so both are named here rather than
# spelled out at each call site.
export PLAYTHROUGH_REQUIREMENTS_LOCK="\
${PLAYTHROUGH_TOOLING_DIR}/requirements.lock"

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
#
# INHERITING ONE IS A TRUST DECISION, AND IT IS VERIFIED BEFORE IT IS
# TAKEN.  `-f` -- the whole of the old test -- says only that a path
# exists, and a caller-supplied credential path that is a symlink, or
# another account's file, or group-readable, hands the display this
# pipeline photographs to somebody else (see
# playthrough_verify_authority_file for each direction).  So the file is
# canonicalised and checked here, at the one place the decision is made,
# and a file that does not pass is NOT inherited: the pipeline falls back
# to its own verified 0600 cookie inside the private runtime root and
# says so, which is the safe direction -- our own authority cannot
# authenticate us to somebody else's server, so the failure surfaces as
# a display that refuses us rather than as a credential we leaked into.
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
# WHERE THE GRID REALLY SAT, MEASURED.  Those two sentences pull in
# different directions -- a grid blitted at the top-left leaves ONE
# eight-pixel band at the bottom, while a centred one leaves two of four
# -- and the committed captures settle it in favour of the first.  Over
# all 395 frames of the recorded session, 387 carry ink in y0-3, 356
# carry ink in y1068-1071, and NOT ONE carries ink in y1072-1079: the
# grid sat at +0+0 with all eight leftover pixels at the bottom, because
# openbox gave the borderless window the whole 1920x1080 root and the
# engine blitted from its top-left corner.  The +4 in the crop is
# therefore the CONTRACTED centred placement, not an observation, and it
# is kept because it costs nothing: the crop is 1072 rows tall and the
# clock row it exists to capture is at y288, far inside it either way,
# and ocr_clock.py measures the grid's true vertical phase against the
# game's own font rather than trusting any computed offset.
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
# WHICH TILESET, DECIDED ONCE, ON THE PLAN'S OWN WORDS.  The Agent Action
# Plan says two things about artwork, and a review was right that leaving
# them both standing left the implementation choosing for itself.  They
# are resolved here, for every consumer, and the resolution is a reading
# of the plan rather than a preference:
#
#   * §0.1.2, last bullet, is an INSTRUCTION IN THE IMPERATIVE, and it is
#     the only place the plan names a specific pack: "You must install
#     the tilesets found in this repository
#     https://github.com/I-am-Erk/CDDA-Tilesets ... and configure the
#     game to use the MSXotto+ Tileset."  It requires an action
#     (install) and a configuration (use MSXotto+).
#   * §0.7.3 and §0.8.2 say ASCIITiles is selected and that no tileset is
#     downloaded or installed.  Both are DESCRIPTIONS OF THE CHECKOUT
#     BEFORE ANY PROVISIONING -- they reason from `.gitignore:52`
#     excluding `/gfx/*` with four negations, i.e. from what git carries,
#     and §0.4.1.3 states that premise in as many words.  A description
#     of the starting state cannot override an instruction about what to
#     do to it, and the instruction is the later, more specific text.
#
# So: MSXotto+ is THE contract, one contract, enforced identically in
# every consumer -- launch_game.sh hydrates and verifies it, seed_options
# writes no other id, capture.sh refuses a production frame under any
# other artwork, and verify_artifacts.sh checks the committed options and
# the installed tree against the tracked provenance anchor.  §0.8.2's
# "no tileset is installed" is therefore superseded in exactly one
# respect and no other: a pack IS installed, into git-ignored gfx/, and
# nothing else in that section is relaxed.
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

# AND WHICH BYTES IT MUST BE, stated OUTSIDE the artwork itself.
# gfx/ is git-ignored (.gitignore:52) with four negations, and this
# tileset is not one of them -- so the artwork every frame of the film is
# rendered in is the one substantive input git does not carry.  A
# security review found the launcher accepting an installed gfx/*
# directory on nothing more than the NAME:/VIEW: line in its own
# tileset.txt: a replaced payload with a regenerated in-pack SHA256SUMS
# was accepted, and so was gfx/MShockXotto+ replaced by a symlink to a
# directory outside the checkout.
#
# An in-pack manifest cannot be the anchor, because it travels with the
# payload: whoever can write the artwork writes the digest list in the
# same command.  So the anchor is TRACKED and outside the tree it
# describes -- playthrough/tooling/tileset_provenance.json, whose
# integrity is git's, exactly like every script in this directory -- and
# it names the upstream repository and exact commit, the compose recipe,
# the id and view, and the size and SHA-256 of every file plus a digest
# over that whole ordered list.  tileset_provenance.py compares the
# COMPLETE installed tree against it and launch_game.sh calls that before
# the tileset is used, on every launch.
#
# THE ANCHOR'S LOCATION IS NOT A TUNABLE, deliberately, and no variable
# below relaxes it: an anchor a caller can point elsewhere is not an
# anchor.  Where the artwork legitimately changes, the anchor is
# regenerated with `tileset_provenance.py generate` and committed as a
# reviewed change.

# Every name the required pack is known by, so a lookup can match the
# id, the view label, or the directory the pack ships as.  This is a
# spelling aid for ONE tileset, not a list of acceptable alternatives.
export PLAYTHROUGH_TILESET_ALIASES="MshockXottoplus MSXotto+ MShockXotto+"

# THERE IS NO SECOND TILESET IN THIS PIPELINE, and there is deliberately
# no variable naming one.  A diagnostic ASCIITiles path used to live here,
# reachable only under PLAYTHROUGH_ALLOW_TILESET_FALLBACK=1 and recorded
# as origin=fallback -- and a review was right that carrying the losing
# side of the requirement conflict at all left two artwork branches in a
# feature whose requirement names exactly one.  The whole branch is gone:
# no variable, no bypass, no code path.  A host without the pack gets a
# refusal that says how to install it, which is the honest outcome,
# because an ASCII capture looks like a perfectly good frame and would
# fail the requirement invisibly.

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

# ---------------------------------------------------------------------
# THE PYTHON DEPENDENCY CLOSURE -- ONE ASSERTION, TWO CONSUMERS
#
# A review found the closure being "verified" by reading the
# interpreter's version string and nothing else: verify_artifacts.sh
# reported "the verified interpreter runs" and run_pipeline.sh asserted
# that PLAYTHROUGH_PYTHON was executable, and between them neither
# established that ANY of the six declared libraries was installed, let
# alone at the declared version.  Section 0.9.1's R9 gate is "pip install
# -r resolves cleanly", and section 0.10.2's reproducibility practice is
# exact `==` pins precisely so that "a future MoviePy release cannot
# silently change the rendered movie while every gate still reported
# green" -- which is exactly what an unchecked closure permits.
#
# WHY THE PROGRAM LIVES HERE.  Two stages need this answer: the gate,
# which reports it as verdicts, and the sequencer, which must refuse to
# produce artifacts without it.  Two implementations of one assertion is
# how they come to disagree, so the program is defined once, in the file
# that is already the single definition of the environment contract, and
# each caller materialises and runs it.  Neither owns it.
#
# WHAT IT ESTABLISHES, in the order the verdicts come out:
#
#   1. The interpreter is CPython 3.12 -- the ABI the lock's wheels were
#      built for.  numpy and Pillow ship per-interpreter binaries, so a
#      3.13 interpreter cannot be running what the lock installed.
#   2. The declaration and the lock pin the same version of all six.
#   3. Each of the six is INSTALLED at that version, read from the
#      interpreter's own distribution metadata.
#   4. Each of the six IMPORTS -- metadata can survive a half-removed
#      package, and an import is the thing the pipeline actually does.
#   5. Every installed distribution's own requirements are satisfied:
#      `pip check` in substance, done through importlib.metadata and
#      packaging rather than by spawning pip, so it needs no network and
#      no pip in the environment.
#
# The verdicts are emitted in the field-separated shape the gate already
# consumes, with the separator passed in, so this file carries no
# knowledge of the gate's protocol beyond "four fields, one line each".
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

# The distribution name declared in requirements.txt, mapped to the
# module name an import statement actually uses.  They differ for two of
# the six, which is why this mapping is written down rather than derived:
# pillow imports as PIL, and imageio-ffmpeg as imageio_ffmpeg.
MODULES = [
    ("moviepy", "moviepy"),
    ("pillow", "PIL"),
    ("pytesseract", "pytesseract"),
    ("numpy", "numpy"),
    ("imageio", "imageio"),
    ("imageio-ffmpeg", "imageio_ffmpeg"),
]
PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s\\;#]+)")

# The first Pillow release that carries the fix for the advisories the
# pinned 11.3.0 is exposed to -- CVE-2026-25990 (HIGH) first fixed in
# 12.1.1, with further records first fixed in 12.2.0 and 12.3.0.  It is
# a CONSTANT HERE AND A GATE BELOW rather than a sentence in
# requirements.txt, because the trigger for moving the pin was written
# down as prose ("when a moviepy release lifts the pillow<12.0 cap")
# and prose does not fire.  Check 6 fires.
PILLOW_FIRST_FIXED = "12.1.1"

# The bootstrap tools belonging to the interpreter.  These are NOT in
# the lock and must not be: pip installs the lock, so it cannot be an
# entry in it.
# They are the ONLY distributions allowed to be present without being
# declared, and naming them here is what lets check 7 refuse everything
# else instead of accepting whatever happens to be installed.
BOOTSTRAP = ("pip", "setuptools", "wheel")

# The one executable startup file the closure is permitted to contain,
# by sha256 of its exact bytes.
#
# A `.pth` file whose line begins `import` is EXECUTED by the site
# module at every interpreter startup, before any pipeline code runs --
# so it is a code-execution vector that no version pin and no hash on a
# wheel describes.  setuptools ships exactly one, to keep its distutils
# shim ahead of the one in the stdlib, and it is allowed by digest
# rather than by
# name: allowing it by name would allow ANY content under that name,
# which is precisely the substitution worth refusing.
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
    except Exception as err:                                # noqa: BLE001
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
    except Exception as err:                                # noqa: BLE001
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
except Exception as err:                                    # noqa: BLE001
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
            except Exception:                               # noqa: BLE001
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

# 6  THE PIN THAT IS FORCED, AND STOPS BEING FORCED WITHOUT NOTICE.
#
# pillow 11.3.0 is pinned because moviepy 2.2.1 declares
# `pillow<12.0,>=9.2.0` and 2.2.1 is the newest moviepy there is -- so
# 11.3.0 is the newest Pillow the declared render stack permits, and it
# carries published advisories that are first fixed in 12.1.1.  That is
# an accepted, disclosed risk for exactly as long as the constraint
# forces it, and NOT ONE DAY LONGER.
#
# The failure this closes is a silent one: the day a moviepy release
# lifts the cap, nothing in this pipeline would notice, and the
# justification for the pin would quietly become false while every gate
# still reported green.  So the justification is measured instead of
# recited -- read from the INSTALLED metadata of the thing that imposes
# it, with no network -- and the moment it stops holding, this FAILS and
# names the move to make.
try:
    from packaging.requirements import Requirement as _Req
    from packaging.utils import canonicalize_name as _canon
    from packaging.version import Version as _Ver
except Exception as err:                                    # noqa: BLE001
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
    except Exception as err:                                # noqa: BLE001
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

# 7  NOTHING IS INSTALLED THAT THE LOCK DOES NOT NAME.
#
# Checks 2-5 all ask "is what we declared present and coherent".  None
# of them asks the opposite question, and it is the one that matters for
# a supply chain: what ELSE is in here.  An extra distribution is a
# package nothing declared, nothing hash-pinned and no review saw, and
# it can be imported by any module in the closure.
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
    except Exception as err:                                # noqa: BLE001
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

# 8  NOTHING RUNS AT INTERPRETER STARTUP THAT WAS NOT ALLOWED.
#
# A .pth file in site-packages whose line begins `import` is executed by
# the site module on EVERY interpreter start, before main() and before
# any check in this program. It is arbitrary code inside the closure
# that no wheel hash and no version pin describes, so it is inventoried
# here by digest.
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
except Exception as err:                                    # noqa: BLE001
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
#   Materialise the shared closure checker at PATH.  Callers put it in
#   their own private scratch directory rather than in the working tree,
#   because a stage that added an untracked file to the evidence is a
#   stage the acceptance gate would, correctly, report.
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
#
# Several checks in this pipeline can be relaxed for diagnosis: an
# interpreter or tool that cannot be verified, a display this pipeline
# did not start and cannot prove is authenticated, a tileset pack on a
# world-writable path, artwork other than the required MSXotto+, a
# Pillow older than the pin, a compiler the project does not sanction,
# and a host whose release no longer receives security fixes.  Each of
# those exists for a real reason -- without them this pipeline cannot be
# debugged on a host it does not own -- and each was, until now,
# enforced only by a WARNING that said not to record a session under
# it.
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
#   PLAYTHROUGH_TRUST_UNVERIFIED   security checks that could not run
#   PLAYTHROUGH_RUNTIME_UNTRUSTED_ANCESTOR
#                                  the first group- or world-writable
#                                  non-sticky directory on the road to
#                                  the private runtime anchor, or empty
#   PLAYTHROUGH_REPO_UNTRUSTED_ANCESTOR
#                                  the same measurement for the road to
#                                  the checkout, set by
#                                  playthrough_check_path_ancestry
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
# statement about the past.  The cost is a loop over the registry's names.
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
    export PLAYTHROUGH_TRUST_UNVERIFIED="${PLAYTHROUGH_TRUST_UNVERIFIED-}"
    # THE SECOND INPUT, and it is not a bypass.  A bypass is somebody
    # deciding to proceed without a check; this is a check that COULD NOT
    # BE PERFORMED -- no `stat` to read an owner with, a utility owned by
    # a third account -- and the two used to be treated differently:
    # the first held the state at diagnostic while the second warned and
    # left it at "trusted".  An inability to verify is not a
    # verification, so it lands in the same state a bypass does, and
    # playthrough_assert_trusted refuses the launch and the capture on
    # either.
    #
    # AN UNSAFE PATH ANCESTRY IS NOT A THIRD INPUT HERE, and that is a
    # deliberate placement rather than an omission.  It is a property of
    # the HOST, like an end-of-life platform, and this file handles those
    # the same way: the property is measured, a stage that is about to
    # produce evidence REFUSES on it, and the waiver that proceeds anyway
    # is a bypass -- PLAYTHROUGH_ALLOW_UNSAFE_PATH_ANCESTRY -- which then
    # reaches the trust state through the loop above like every other
    # one.  Keying the state on the measurement directly would make
    # merely SOURCING this file on such a host report a diagnostic
    # environment before anything had been asked of it, and sourcing is
    # supposed to be inert.  See playthrough_check_path_ancestry.
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
#   Returns 0 when no bypass is active; otherwise explains every active
#   one and refuses, returning 1 (this file is sourced, so it cannot
#   exit -- the caller turns the refusal into its own exit code).
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
#
# Named here so that a missing-tool diagnostic can say what to
# install rather than only what is absent.  A reader who is told
# "xdpyinfo is missing" still has to go and find out that it lives in
# x11-utils; being told the package is the difference between a
# two-minute fix and a search.  The list is the apt block in
# playthrough/tooling/requirements.txt, which is the single inventory
# of the system packages this pipeline needs.
#
# EVERY IMAGEMAGICK ENTRY POINT IS NAMED, not just the ones the capture
# path uses.  `compare` was missing from that arm, so an operator whose
# host lacked it was told to install "unknown package" -- the one answer
# this table exists to avoid -- while `convert` and `identify`, which
# ship in the very same package, were named correctly.  A table that is
# right about two thirds of a package is worse than no table, because it
# reads as authoritative.
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
#   BOTH GENERATORS ARE RESOLVED BY VERIFIED ABSOLUTE PATH.  A review
#   noted that the cookie helpers were not all authority-verified, and the
#   consequence is specific rather than theoretical: whatever produces
#   these sixteen bytes decides whether the display's only credential is
#   unguessable, so a `mcookie` earlier on PATH than the packaged one is
#   in a position to hand out a cookie it already knows.  Every other
#   external command in this file goes through playthrough_require_tools,
#   which verifies ownership and mode and exports a checked
#   PLAYTHROUGH_BIN_<NAME>; these two now do the same.
#
#   The fallback is not a lesser cookie -- sixteen bytes of /dev/urandom
#   is the same strength mcookie provides -- it exists so a host without
#   util-linux still gets a real random value instead of something
#   derived from the clock.
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
#
#   A DIGEST, NEVER THE COOKIE.  This value is written into the ownership
#   record and quoted in diagnostics, and the cookie itself is the
#   credential that lets its holder read the screen being captured and
#   inject keystrokes into the session.  A digest answers the only
#   question the record needs to ask -- "is the cookie in the file still
#   the one the recorded server was started with" -- and answers it
#   without putting the credential anywhere a log can reach.
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
#
#   This is what makes an authenticated X server possible: the server is
#   started with -auth pointing at this same file, so only a client that
#   can read it may connect.  The file is created 0600 inside the
#   verified private runtime root -- a credential in a shared directory
#   is not a credential.
#
#   AN INHERITED AUTHORITY IS READ, NOT WRITTEN.  It used to be "added to
#   rather than replaced", which sounds conservative and is not: adding an
#   entry means writing into a file this pipeline does not own the
#   lifecycle of, through a path the caller chose, and xauth writes
#   through a symlink.  It is verified again here -- the check is cheap
#   and the file may have changed since env.sh was sourced -- and if it
#   carries no cookie for the contracted display the run REFUSES rather
#   than repairing somebody else's credential.  The refusal names the
#   three ways out, one of which (PLAYTHROUGH_ALLOW_INHERITED_XAUTH_WRITE)
#   is an explicit, verified opt-in: it still requires the file to pass
#   verification, so the opt-in buys the write, never the trust.
#   A FRESH COOKIE PER SERVER GENERATION, when asked for one.  A review
#   found that this returned early whenever ANY MIT cookie for the display
#   already existed, and measured the consequence on this host: the cookie
#   in the authority file was written at 18:54 on one day and the three
#   Xvfb processes answering for the display had all started later.  A
#   cookie that outlives the server it authenticated is a credential whose
#   history nobody can account for -- it may have been left by a previous
#   generation, or planted -- and adopting it silently means the new server
#   is started with a secret this run did not choose.
#
#   So the bring-up path calls this as `playthrough_ensure_xauth fresh`,
#   immediately before Xvfb is exec'd, and a fresh cookie REPLACES any
#   prior entry for the display.  Every other caller asks for no rotation
#   and gets the existing cookie, which is not laxity: -auth is read once
#   at exec, so rotating under a running server would leave that server
#   accepting the old value while every new client presented the new one.
#   Rotation belongs to the one moment a server is about to be created.
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
        # ROTATION IS ONLY EVER DONE TO AN AUTHORITY FILE THIS PIPELINE
        # OWNS.  An inherited file's lifecycle belongs to whoever provided
        # it, and removing an entry from it would break clients this run
        # cannot see; the opt-in below buys an `add`, never a `remove`.
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
    # -auth is as load-bearing as -nolisten tcp: one closes the network
    # socket, the other the local one.  playthrough_spawn_detached is
    # what makes the server survive a signal aimed at this shell AND
    # proves it is alive before returning.
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
# up" are different facts, and until a review pointed it out only the
# first was ever established.  The difference matters twice over:
#
#   * a display somebody else provisioned may be shared, may be
#     restarted under the session, and may already have clients on it --
#     none of which this pipeline can see, and any of which breaks the
#     one-keystroke-one-frame invariant without leaving a trace;
#   * on a host running several checkouts, an unsuffixed CLONE_INDEX
#     mistake puts two of them on one server, where each would capture
#     the other's screen.
#
# So when this pipeline starts the server it RECORDS that, in the private
# runtime root, with enough identity to be checked later: the display,
# the checkout that started it, the pid, and what kind of owner it is.
# A production launch requires that record; a display without one is
# usable for DIAGNOSIS and is registered as an unverifiable security
# check, which holds the trust state at diagnostic exactly as a bypass
# does -- so launch_game.sh will not capture from it and capture.sh will
# not keep a frame taken on it.  Nothing is killed, nothing is taken
# over: a foreign display is left alone and merely not trusted.
# ---------------------------------------------------------------------

# playthrough_x_ownership_record
#   The path of the ownership record for the contracted display.
playthrough_x_ownership_record() {
    printf '%s' "${PLAYTHROUGH_RUN_DIR}/x-ownership${PLAYTHROUGH_DISPLAY_NUM}"
}

# playthrough_signal_pid KIND PID [SIGNAL]
#   Signal a process THROUGH A HANDLE, never through its number.
#
#   THE RACE THIS CLOSES, IN ITS OWN WORDS (CWE-367).  Teardown used to
#   verify a pid -- alive, the expected program, owned by this account --
#   and then run `kill "${pid}"`.  Everything between those two steps is
#   a window: if the process exits inside it and the kernel hands the
#   number to something else, the signal goes to a stranger.  Running as
#   root, that is not a failed teardown; it is killing somebody else's
#   process.  A previous remediation narrowed the window to a few
#   syscalls and said so honestly in TECHNICAL_NOTES.md -- "narrowed, not
#   closed" -- because bash has no pidfd.  Bash does not need one: the
#   pipeline already REQUIRES a verified interpreter, and Python has had
#   os.pidfd_open and signal.pidfd_send_signal since 3.9.
#
#   HOW THE HANDLE MAKES IT SAFE.  os.pidfd_open() pins THAT PROCESS: the
#   descriptor refers to the process itself and not to the number, so it
#   cannot be inherited by a later occupant of the number.  The identity
#   checks run AFTER the handle is held, and the signal is delivered
#   through the handle -- so between validating and signalling there is no
#   number left to recycle.  If the process has exited by then,
#   pidfd_send_signal reports ESRCH and nothing is signalled at all.
#
#   FAIL-SAFE, NOT FAIL-OPEN.  A kernel or interpreter without pidfd
#   support gets a REFUSAL and a diagnosis naming what to stop by hand;
#   it does not fall back to signalling a number, because "signal by
#   revalidated number alone" is precisely the defect.  Exit statuses:
#   0 signalled, 1 not signalled and why on stderr, 2 pidfd unavailable.
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
#   True when PID is alive and its executable name is KIND.  /proc is
#   read directly because `ps` is not in the pipeline's tool contract and
#   an ownership check that needs a package to be installed is one more
#   thing that can silently not happen.
#
#   THIS IS A NECESSARY CONDITION AND NOT A SUFFICIENT ONE, and callers
#   deciding ownership must not stop here.  A command NAME is not an
#   identity: Linux recycles pids, and "some process called Xvfb is alive
#   at 962316" is a different claim from "the Xvfb we started at 962316 is
#   still that process".  A review measured the gap on this very host --
#   THREE Xvfb processes answering for one display, with distinct start
#   times, while the pidfiles named one pair -- so an ownership decision
#   taken on comm alone would have signalled whichever of the three
#   happened to hold the recorded number.  playthrough_pid_identity below
#   is the whole answer; this is the cheap first half of it.
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
#
#   NUL-separated on disk, so the separators become spaces; and the
#   result is held to a printable single-line grammar before it is
#   returned, because it is written into a record this pipeline reads
#   back line by line and a value carrying a newline would forge a field.
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
#   Print a process's full identity as one line, or nothing:
#
#     <comm> <starttime> <uid> <resolved exe> <cmdline>
#
#   WHY ALL FIVE.  Each closes a hole the others leave open: comm is
#   trivially forgeable by any process that renames itself; the start
#   time makes (pid, starttime) unique for the life of a boot and so
#   defeats pid recycling; the uid says whose process it is; the resolved
#   executable says WHICH Xvfb, since a second one earlier on PATH is a
#   different program with the same name; and the argument vector carries
#   the display and screen the server was actually asked for.
#
#   Printed as one line so a caller can record it and compare it whole,
#   which is the comparison that cannot be partly done by accident.
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
#
#   THE SOCKET IS THE DISPLAY'S OWN IDENTITY, independent of any pid.  A
#   server that died and was replaced leaves a NEW socket inode behind, so
#   comparing it against the one recorded at bring-up answers "is the
#   thing answering on :99 still the thing we started" without trusting a
#   process table at all.  On this host the socket outlived two later Xvfb
#   generations that never bound it, which is exactly the confusion this
#   field removes.
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
#   'pipeline' for a server this shell's process tree owns, or
#   'supervisor' for the provisioned durable service, which this checkout
#   asked for and can restart.
#   THE PROCESS IDENTITY IS RECORDED, NOT JUST ITS NUMBER.  A review found
#   the record carrying only (display, kind, pid, repo, screen, authority,
#   recorded), and the ownership check comparing the pid against
#   /proc/PID/comm alone -- so any process that happened to hold the
#   recorded number and be called Xvfb would be treated as the server this
#   pipeline started, and signalled as such by the teardown.  Measured on
#   this host: three Xvfb processes for one display with distinct start
#   times.  So the identity written here is the whole of
#   playthrough_pid_identity, plus the socket the display is actually
#   answering on and the digest of the cookie the server was started with.
playthrough_record_x_ownership() {
    local kind="${1:-pipeline}"
    local pid="${2-}"
    local record identity="" socket="" cookie=""
    record="$(playthrough_x_ownership_record)"
    # THE IDENTITY IS READ BEFORE THE FILE IS CREATED, so a refusal leaves
    # nothing behind at all.  Creating the record first and then refusing
    # left an EMPTY file where a later run would look for a claim --
    # harmless, because a record with no fields reads as foreign, and
    # still the wrong shape for a refusal that says nothing was recorded.
    if [ -n "${pid}" ]; then
        identity="$(playthrough_pid_identity "${pid}")" || identity=""
        if [ -z "${identity}" ]; then
            # A pipeline-owned server whose identity cannot be read is not
            # recordable: the record would then claim an ownership no
            # later run could check, which is worse than no record at all
            # (a missing record degrades the trust state, and a false one
            # would not).
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
#     pipeline    this checkout started the server; its pid is alive and
#                 is an Xvfb process
#     supervisor  the provisioned durable service serves it for this
#                 checkout
#     stale       a record exists for this checkout but the process it
#                 names is gone, so whatever is answering now is not the
#                 server that was recorded
#     foreign     something is answering and no record claims it
#     absent      nothing is answering
#     replaced   a record exists and its process is alive, but the
#                identity, the socket or the cookie no longer match what
#                was recorded -- so something OTHER than the recorded
#                server is what a client would now reach
#
#   REPLACED IS REPORTED SEPARATELY FROM STALE, and the distinction is the
#   review's finding made legible.  `stale` means the recorded process is
#   gone; `replaced` means a process is there and is not the one we
#   recorded.  Both are refusals -- neither is `pipeline` -- but they send
#   an operator to different places, and collapsing them into "not ours"
#   would hide the case a recycled pid produces.
#
#   PLAYTHROUGH_X_OWNERSHIP_REASON carries the detail, because a one-word
#   state cannot say WHICH field disagreed and that is exactly what an
#   operator needs next.
#
#   IT IS PUBLISHED IN A VARIABLE AS WELL AS PRINTED, and a caller that
#   wants the reason must NOT use command substitution.  `state="$(...)"`
#   runs the function in a subshell, so every variable it sets dies with
#   that subshell -- which is how the reason came back empty the first
#   time it was measured.  The printed word stays the contract for callers
#   that only want the state; a caller wanting both does:
#
#       playthrough_x_ownership_state >/dev/null || true
#       state="${PLAYTHROUGH_X_OWNERSHIP_STATE}"
#       why="${PLAYTHROUGH_X_OWNERSHIP_REASON}"
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
            # A RECORD WITHOUT AN IDENTITY IS NOT TRUSTED.  Records written
            # before the identity field existed cannot be revalidated, and
            # treating an unverifiable claim as ownership is the whole
            # defect being fixed -- so it is reported as replaced rather
            # than accepted on the strength of a pid and a name.
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
            # AND THE COOKIE THE SERVER WAS STARTED WITH.  -auth is read
            # once, at exec; a cookie replaced afterwards leaves the
            # running server accepting the OLD one, so a mismatch means
            # the authority file no longer describes this server.
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
#   Establish ownership or register the inability to.  Never fatal on its
#   own: the refusal belongs to the capture gate, which reads the trust
#   state, so that diagnosis on a foreign display keeps working while
#   nothing recorded on one can be mistaken for evidence.
playthrough_assert_x_ownership() {
    local state
    # NOT `$( )`: the reason is set INSIDE the function, and a command
    # substitution would run it in a subshell where every variable it sets
    # dies.  Measured that way -- the state came back and the reason came
    # back empty.
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
            # THE CASE A PID-AND-NAME CHECK CANNOT SEE.  A process IS
            # alive under the recorded number and it is not the one that
            # was recorded -- a recycled pid, a different Xvfb binary, a
            # server that died and was replaced, or a cookie rotated out
            # from under the running one.  Reported in its own right
            # because it sends an operator somewhere different from
            # `stale`, and because a review measured three Xvfb processes
            # answering for one display on this very host.
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
#
# Everything under the private runtime root is diagnostic: lock files,
# pid files, the per-stage stderr captures, the scratch directories a
# gate opens.  None of it is evidence, and none of it was ever removed --
# so a long-lived host accumulated 1 021 lock files and 13 orphaned
# capture-stage error files, measured by a review, none of which any
# reader could tell from a live one.  That is two faults: the noise, and
# the fact that "is this lock held?" had no answer.
#
# The rule below is deliberately narrow, because a pruner in a directory
# that also holds a live X cookie and live pid files is one bad glob away
# from breaking a running session:
#
#   * only four shapes are considered, all of them this pipeline's own
#     leftovers, matched by exact patterns rather than by a wildcard
#     sweep of the directory;
#   * a lock file is removed only after `flock -n` PROVES nothing holds
#     it, which is also the diagnosis an operator wants;
#   * age is required as well -- a closed lock from thirty seconds ago
#     probably belongs to the command that just finished;
#   * the X socket is NEVER touched.  A live socket with a dead server
#     behind it is reported, not deleted: removing one that is in fact
#     live takes the display out from under a running session, and the
#     server recreates the file itself when it is genuinely restarted.
# ---------------------------------------------------------------------

# playthrough_lock_is_held PATH
#   True when some process holds the advisory lock on PATH.  Asks the
#   kernel with a non-blocking flock in a subshell, so the answer costs
#   nothing and this shell never ends up holding the lock it asked about.
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
#
#   WHY THIS EXISTS, AND WHY `flock -n` IS NOT ENOUGH.  A lock is held by
#   an open file description, so unlinking the file another process is
#   BLOCKED ON does not merely lose a file: the waiter's descriptor still
#   refers to the old inode, the next acquirer creates a new one at the
#   same name, and the two of them then "hold" a lock neither can see the
#   other holding.  `flock -n` answers "does anyone hold it", which
#   deliberately says nothing about a process that has the file open and
#   is waiting for it.  This answers the question the pruner actually has
#   to ask before it removes anything: is this path still connected to a
#   running process at all.
#
#   Only processes whose /proc entry THIS uid can read are considered,
#   and that is a deliberate bound rather than an oversight: the runtime
#   root is 0700 and owned by this uid, so nothing but this uid's own
#   processes -- and root -- can have a descriptor inside it, and this
#   pipeline never runs a stage as root that another account started.
#   Treating an unreadable foreign process as a holder would disable
#   pruning entirely on any busy host, which trades a real leak for an
#   imagined one.
#
#   THIS IS USED INSTEAD OF "ACQUIRE EVERY CONTAINED LOCK", and on purpose.
#   Acquiring each lock would prove nothing holds them at that instant and
#   would leave the pruner itself holding locks it then has to drop --
#   during which a stage could legitimately be waiting for one, get it,
#   and start working inside a directory the pruner is about to remove.
#   Proving nothing has the path OPEN is the stronger statement: it covers
#   the holder, the waiter, and the process that has merely opened a
#   journal to read it, none of which an acquisition distinguishes.
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
#
#   A PID ALONE IS NOT AN IDENTITY.  Linux recycles them, so "pid 4242 is
#   alive" and "the pid 4242 we recorded is alive" are different claims,
#   and a check that conflates them will one day report a stranger's
#   process as this pipeline's own.  The start time is the missing half:
#   the pair (pid, starttime) is unique for the life of a boot.
#
#   Field 22 is read by first discarding everything up to and including
#   the LAST ')' of field 2, because a process name may itself contain
#   spaces and parentheses and no field-splitting survives that.
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
#   Diagnose the display's UNIX socket, which is the one thing that can
#   disagree with "a server is answering":
#
#     serving   the socket exists and the server answers
#     stale     the socket exists and nothing answers -- an orphan from a
#               server that died without unlinking it
#     foreign   the socket exists, nothing answers, and it belongs to
#               another account, so it is not ours to reason about
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
#   The operator-facing form of the state above.  Called on the failure
#   path of a display wait, where "nothing is answering" is exactly the
#   moment the difference between no socket and an orphaned socket
#   decides what to do next.
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
#   Remove this pipeline's own closed leftovers from the runtime root.
#   Bounded by shape and by age, silent about what it keeps, and a no-op
#   when `find` is unavailable.  Never fatal: a pruner that stops a run
#   would be worse than the mess it tidies.
#
#   The window is PLAYTHROUGH_RUNTIME_RETENTION_MINUTES (default one
#   day), read from the environment rather than taken as an argument so
#   that there is exactly one way to set it and every caller is the same
#   call.
# playthrough_holds_live_lock DIRECTORY
#   True when DIRECTORY contains a lock file some process still holds.
#   One level only: every lock this tree creates sits directly in the
#   directory it protects.
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
#   and each producer's `<stage>.generation.json` -- because a pattern
#   loose enough to catch `phase.json` would make a rebuildable cache
#   block a prune for ever.
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
    #
    #    AND SO ARE OPEN-BUT-UNHELD ONES.  `flock -n` answers "does
    #    anyone hold it" and says nothing about a process that has the
    #    file OPEN and is blocked waiting for it -- and unlinking the
    #    file under a waiter is how a lock stops being a lock: the
    #    waiter keeps a descriptor on the old inode, the next acquirer
    #    creates a new one at the same name, and the two of them then
    #    hold "the lock" simultaneously without either being able to see
    #    the other.  So a lock file is removed only when nothing has it
    #    open at all.
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
    #    rather than assumed dead because the file is old.  A long-lived
    #    stage's diagnostics are exactly the ones worth keeping, and a
    #    recycled pid can only cause a dead stage's file to be KEPT,
    #    never a live stage's file to be removed, which is the direction
    #    a pruner should err in.
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
    #    under a prefix absent from here is the unbounded accumulation
    #    this pruner exists to end, reappearing under a new name.  The
    #    exit trap in each stage is the primary cleanup and this is the
    #    backstop for a run that was killed outright, so both are needed.
    #    Anything else in the runtime root is left exactly where it is.
    #
    #    THREE REFUSALS GUARD THIS `rm -rf`, because a scratch directory
    #    is not only scratch.  The session's holds `step.json` -- the
    #    journal recording a keystroke that may already have reached the
    #    game -- and each producer's holds `<stage>.generation.json`, the
    #    record of a publication interrupted mid-switch.  Removing either
    #    does not tidy anything: it destroys the only description of an
    #    in-flight evidence transaction, and nothing afterwards can tell
    #    a completed step from a delivered-but-unrecorded one.  So a
    #    directory that still holds one is KEPT AND NAMED, to be
    #    reconciled deliberately rather than erased by a timer.
    #    `phase.json` is deliberately not in that set: it is a
    #    rebuildable cache of what the sidecar already says, so it never
    #    blocks a prune.
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
#
#   Ownership-aware by construction: the ownership record decides, so a
#   display served by a durable service or by another checkout is
#   reported and left running.  That asymmetry is the point -- bringing a
#   surface up is idempotent and safe, tearing one down is neither.
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
            # `stale`, `replaced` and `foreign` all land here, and all
            # three mean the same thing for a TEARDOWN: this checkout
            # cannot show that what is answering is its own.  Running as
            # root, that is the difference between stopping a server and
            # killing a stranger's process, so nothing is signalled.  The
            # reason is quoted because `replaced` in particular is worth
            # reading -- it means a process IS alive under the recorded
            # number and is not the one that was recorded.
            playthrough_warn "the display ${PLAYTHROUGH_DISPLAY} was" \
                "not started by this checkout (${state}:" \
                "${PLAYTHROUGH_X_OWNERSHIP_REASON:-no detail was" \
                "recorded}), so it is left running.  Stopping" \
                "infrastructure this pipeline does not own would take" \
                "the display away from whoever does."
            return 1
            ;;
    esac
    # NOTHING IS SIGNALLED ON THE STRENGTH OF A PIDFILE.  A review put it
    # exactly: shutdown trusted pidfile values weakly while running as
    # root.  A pidfile is a NUMBER written minutes or days ago, in a
    # directory this pipeline owns but whose contents outlive any process
    # in it -- and on this host the recorded pidfile named one pair while
    # three Xvfb processes were alive.  As root, signalling a recycled pid
    # is not a failed teardown; it is killing a stranger's process.
    #
    # So each number is checked against what it is supposed to BE before
    # anything is sent to it: alive, the expected program, owned by this
    # account, and started when the record says.  A number that does not
    # answer to that is reported and left alone.
    #
    # AND THE SIGNAL ITSELF GOES THROUGH A HANDLE.  Checking a number and
    # then signalling that number leaves a window between the two in which
    # the number can be recycled (CWE-367), and a review was right that
    # narrowing that window is not closing it.  playthrough_signal_pid
    # pins the process with os.pidfd_open first and asks every identity
    # question of the pinned process afterwards, so a recycled number can
    # only produce a refusal.  The checks below are kept in front of it
    # because they produce the DIAGNOSIS an operator needs -- "the number
    # was recycled and here is what holds it now" -- which the handle
    # alone would report only as ESRCH.
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
    playthrough_check_path_ancestry || return 1
    playthrough_assert_video_driver || return 1
    playthrough_require_tools xdpyinfo xprop grep awk || return 1
    playthrough_start_xvfb || return 1
    playthrough_start_wm || return 1
    playthrough_assert_x_access_control || return 1
    # WHO OWNS THE DISPLAY, asked after the server is up and before
    # anything is launched on it.  Deliberately not fatal here -- a
    # foreign display is a legitimate thing to diagnose against -- but it
    # registers itself as an unverifiable security check, so the trust
    # state is diagnostic and the capture gate refuses on its own.
    playthrough_assert_x_ownership || true
    playthrough_assert_display || return 1
    # BOUNDED RETENTION, once per launch rather than at source time.
    # Sourcing this file must not write into anything, and a pruner that
    # ran on every source would be both surprising and a race; a launch
    # is exactly the moment the runtime root is about to be used.
    playthrough_prune_runtime
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
        playthrough_deny_foreign_write "${dir}" \
            "artifact directory" || return 1
    done
    return 0
}

# playthrough_deny_foreign_write PATH [LABEL]
#   Take group and other WRITE access off PATH, announce it if it had
#   any, and confirm the result.  Read access is left exactly as it was.
#
#   THIS IS THE ARTIFACT TREE'S RULE, and it is deliberately weaker than
#   playthrough_secure_dir's 0700.  The two trees are answerable for
#   different things:
#
#     * the RUNTIME root holds a credential, the pid of a live server and
#       full-resolution captures that were withdrawn -- private, so 0700,
#       and readable by nobody else at all;
#     * the ARTIFACT tree holds what is about to be committed to a git
#       repository and read by whoever reads the repository.  Making it
#       owner-only would protect nothing that is not about to be
#       published anyway, and would be theatre.
#
#   What is NOT acceptable in either is foreign WRITE access, and that is
#   the property this enforces.  A security review measured the
#   consequence on the delivered tree: fifteen directories at mode 2777
#   and a hundred and fifty-one files at 0666 -- the survivor's save, the
#   engine's config, the captioned film and the acceptance report among
#   them -- because `mkdir -p` inherits the ambient umask and the engine
#   was launched under a permissive one.  Any local account could have
#   rewritten or deleted the evidence, and nothing would have said so.
#
#   REPAIR AND ANNOUNCE, never repair quietly.  A directory found wider
#   than it should be means something outside this pipeline opened the
#   evidence to other accounts, and the repair is the only moment anybody
#   would learn that happened.  verify_artifacts.sh asserts the same
#   property over the whole tree afterwards, so this is enforcement and
#   that is the audit.
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
#   BASENAME with a short digest of THIS CHECKOUT's root appended, so a
#   lock taken under it excludes a second run over the same working tree
#   and nothing else.
#
#   WHY THE NAME HAS TO CARRY THE CHECKOUT.  PLAYTHROUGH_LOCK_DIR lives
#   under the runtime root, and the runtime root is derived from
#   CLONE_INDEX rather than from the working tree -- so two clones that
#   were both started without CLONE_INDEX share one lock directory, and a
#   bare name like `pipeline` or `checkpoint` therefore serialises two
#   runs that share NOTHING.  Measured: a second checkout's run refused
#   with a message about "this checkout" while the holder was a different
#   checkout entirely, which is a diagnosis that sends an operator to
#   look in the wrong place.
#
#   The digest is of the ABSOLUTE root path, taken with sha256sum and cut
#   to eight hex characters: long enough that two checkouts on one host
#   will not collide, short enough to read in a diagnostic, and stable
#   across runs so the same tree always takes the same lock.  The name is
#   held to playthrough_acquire_lock's own character class -- lowercase
#   hex satisfies it -- and the derivation is here rather than in each
#   caller so the two consumers cannot drift apart.
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
#
#   Check-and-act is the whole problem this solves.  "No game is
#   running, so start one" and "no build is running, so start one" are
#   both two operations, and two invocations that interleave between them
#   end up with two engines writing one save, or two makes writing one
#   object tree.  The lock is held by an open descriptor, so it survives
#   for as long as the shell that took it and is released by the kernel
#   even if that shell dies.
#
#   MODE is 'exclusive' (the default, and what every caller before the
#   mutation lock wanted) or 'shared'.  A SHARED holder excludes every
#   exclusive one and no other shared one, which is exactly the shape a
#   quiescence lock needs: many producers may run beside each other,
#   while a verifier or a committer that takes the same lock exclusively
#   gets the tree to itself and knows nothing changed under it.
#
#   The descriptor is allocated with bash's {var} redirection rather than
#   a fixed number, so nothing in a caller collides with it, and NOT with
#   eval: there is no eval anywhere in this tree.
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
#   TWO DESCRIPTORS, because there are two locks a stage can be holding
#   when it spawns: its own stage lock (PLAYTHROUGH_LOCK_FD) and the
#   checkout's mutation lock (PLAYTHROUGH_MUTATION_LOCK_FD).  The engine
#   inheriting the second would hold the whole checkout shared for its
#   entire life, and every checkpoint -- including the `creation` one the
#   requirements mandate WHILE THE GAME IS RUNNING -- would then block for
#   its full timeout and refuse.  So both are withheld, and both are
#   borrowed from /dev/null when not held, which keeps the spawn one code
#   path instead of four.
#
#   Usage:
#       playthrough_child_close_fd
#       setsid nohup CMD ... {PLAYTHROUGH_CHILD_CLOSE_FD}>&- \
#           {PLAYTHROUGH_CHILD_CLOSE_FD2}>&- &
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
#
#   A REDIRECTION ON AN `exec` WITH NO COMMAND IS APPLIED TO THE SHELL,
#   FOR THE REST OF ITS LIFE.  This line used to read
#
#       exec {PLAYTHROUGH_CHILD_CLOSE_FD}>&- 2>/dev/null
#
#   where the `2>/dev/null` was meant to swallow one possible complaint
#   from the close.  What it actually did was point THE CALLING SHELL's
#   stderr at /dev/null permanently, so every warning, diagnosis and
#   refusal that shell produced after its first detached spawn went
#   nowhere.  Measured, not theorised: a preflight that starts Xvfb and
#   then fails printed its verdict on stdout and NOT ONE WORD of the
#   diagnosis that says which stage failed and why.  It went unnoticed
#   because the borrowed branch only runs when no lock is held, and the
#   scripts that spawn under a lock skip it entirely.
#
#   So the descriptor is closed with NO redirection on the exec at all,
#   and the one complaint that redirection was hiding -- closing a
#   descriptor that is not open, which a second call would do -- is
#   prevented by asking first.  A `{ ... } 2>/dev/null` group is NOT an
#   alternative here: it restores stderr correctly when the close
#   succeeds, but a close that FAILS inside it leaves the shell with the
#   group's redirection still in force, which is the same defect again
#   in a narrower window.
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
    # THE SAME TRAP as playthrough_child_close_done documents at length:
    # `exec {fd}>&- 2>/dev/null` sends this shell's stderr to /dev/null
    # for good, so a script that released its lock and then had something
    # to report reported it into the void.  The lock itself is already
    # dropped by the `flock -u` above, so the worst case here is a
    # descriptor that stays open in a script that is about to exit --
    # which costs nothing, and costs far less than a lost diagnosis.
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
#
# Every lock above this line serialises ONE STAGE against another copy of
# ITSELF: two sequencers, two checkpoints, two launches, two publications
# of the same artifact.  None of them serialises a stage against a
# DIFFERENT stage, and that is the gap this closes.
#
# The gap, stated as the sequence that produced it: the gate reads the
# whole artifact tree and passes; a producer -- a session step appending
# a frame and a row, or a renderer republishing the movie -- changes the
# tree; the committer then stages and publishes state that no gate ever
# saw.  Every individual lock was held correctly throughout, because no
# two holders were ever the same stage.  A checkpoint taken between a
# `verify` that passed and a `commit` that ran is not evidence of
# anything if the tree moved in between, and nothing in the arrangement
# above could notice that it had.
#
# So there is one lock per checkout, and the two roles take it
# differently:
#
#   PRODUCERS take it SHARED.  The session step (its whole transaction,
#   from recovering the counter to the last append), each artifact
#   publication, the caption mux, and the launch of the engine.  Shared
#   holders do not exclude each other, which is right: they already
#   exclude each other where they must, through their own stage locks.
#
#   THE VERIFIER AND THE COMMITTER take it EXCLUSIVE, and the sequencer
#   holds it exclusively ACROSS both of them -- which is the only way the
#   sequence above is closed, because two separate exclusive windows
#   leave the same hole between them that this lock exists to remove.
#
# WHAT IT DOES NOT COVER, said plainly rather than left to be discovered.
# The engine is a detached process that writes into playthrough/userdir/
# for its whole life, and the `creation` checkpoint is mandated while it
# is still running -- so no lock this pipeline holds can make that tree
# quiescent, and pretending otherwise would be the dishonest version of
# this control.  Three things bound that residue instead: the launch
# itself holds the lock shared across the spawn and the window wait, so
# the engine's one unbounded burst of writes (its first-run
# configuration) cannot land inside a checkpoint; the engine advances
# only when a step sends it a key, and a step holds the lock; and the
# committer binds the published tree to the index it validated
# (assert_commit_tree_matches_index in commit_artifacts.sh), so anything
# the engine writes after staging is simply not in that commit rather
# than silently part of it.
#
# RE-ENTRANCY IS A CORRECTNESS REQUIREMENT, NOT A CONVENIENCE.  A lock is
# held by an open file description, so a child that inherits the
# descriptor and then opens the same file again is a DIFFERENT
# description -- and `flock` on it blocks against its own parent, for
# ever.  The sequencer runs the verifier and the committer as children
# while holding the lock, so without a re-entrancy path the sequencer
# would deadlock on itself on its first run.
#
# The marker is not trusted, it is VERIFIED.  A child that finds
# PLAYTHROUGH_MUTATION_LOCK_HELD in its environment proves the claim
# before acting on it: the descriptor it names must still be open in this
# process and must resolve to this checkout's lock file, and a
# non-blocking exclusive probe on a FRESH descriptor must fail, which is
# the kernel confirming that something really does hold it.  A marker
# that cannot be proved is a REFUSAL rather than a fallback to acquiring:
# a caller who set it by hand is either mistaken about what is running or
# trying to make a stage skip its lock, and neither deserves a lock this
# process would then release out from under its ancestor.
# ---------------------------------------------------------------------

PLAYTHROUGH_MUTATION_LOCK_BASENAME="mutation"
# BOTH OF THESE ARE INITIALISED CONDITIONALLY, and the reason is the
# whole re-entrancy mechanism.  A child sources this file too, so a plain
# `PLAYTHROUGH_MUTATION_LOCK_FD=""` here would erase the one piece of
# evidence the child has that its parent holds the lock -- measured: the
# child then refused with "there is no descriptor to check the claim
# against" while the descriptor was sitting open on its own fd 10.
# PLAYTHROUGH_MUTATION_LOCK_OWNED is deliberately NOT exported, so the
# `:-0` reads as 0 in every child and as itself on a re-source: a child
# must never believe it owns what it merely inherited, because releasing
# it would leave the ancestor thinking it still had the tree to itself.
PLAYTHROUGH_MUTATION_LOCK_FD="${PLAYTHROUGH_MUTATION_LOCK_FD:-}"
PLAYTHROUGH_MUTATION_LOCK_OWNED="${PLAYTHROUGH_MUTATION_LOCK_OWNED:-0}"
# How long to wait for the other role.  Generous, because a render or a
# long session legitimately holds it for minutes, and an unbounded wait
# is a hang nobody can diagnose.
PLAYTHROUGH_MUTATION_LOCK_TIMEOUT_DEFAULT=900

# playthrough_mutation_lock_path
#   This checkout's mutation lock file.  Derived from the same digest the
#   sequencer and the checkpoint locks use, so two clones do not contend
#   and two runs over one tree always do.
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
#
#   The asymmetry is the whole point: a stage that needs the tree to
#   itself must NOT proceed on the strength of a shared hold, because a
#   producer could be writing beside it at that very moment.  flock can
#   convert a shared hold to an exclusive one on the same descriptor, but
#   two holders converting at once deadlock, so an upgrade is refused as
#   the programming error it is rather than attempted.
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
#
#   PLAYTHROUGH_LOCK_FD is saved and restored around the acquisition, so
#   a caller that already holds its own stage lock through that variable
#   keeps it: the mutation descriptor lives in its own variable precisely
#   because two locks held at once must not share one name.
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
#   process did not take would leave the ancestor believing it still had
#   the tree to itself, which is worse than never having locked at all.
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
# playthrough_os_release_source below.  An earlier pass added a
# second, `playthrough_os_release_path`, which returned
# $PLAYTHROUGH_OS_RELEASE whenever it was set; it is deleted rather
# than left unused, because the two differed in the one respect that
# matters -- the survivor honours a nomination ONLY in a tree git
# does not track, so a real checkout reads its own host and cannot
# be told otherwise, and a caller reaching for the weaker twin would
# have silently undone that.

# playthrough_os_release KEY
#   Read one KEY=value out of the platform source, unquoted, or print
#   nothing.  The file is PARSED rather than sourced: sourcing executes
#   it, and a check whose whole purpose is to reduce risk should not add
#   an execution path of its own.  KEY is restricted to the shape the
#   specification uses, so nothing can be smuggled into the expression.
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
#
#   WHY A NOMINATION EXISTS AT ALL.  This pipeline's own regression
#   suites run the real scripts against a FABRICATED checkout in a
#   temporary directory, with stub tools and a fake engine, and they have
#   to exercise the production paths -- a suite that could only reach the
#   prerequisite refusal would assert nothing about its subject.  Those
#   runs are not claims about a host, so they need to be able to say
#   which host the check should believe.
#
#   AND WHY IT IS NOT A HOLE.  Two conditions, both verified rather than
#   declared.  The file is read only if it is a REGULAR FILE and NOT a
#   symbolic link -- a link can be repointed between this resolution and
#   the read, so what the gate measured would not be what was nominated
#   -- and anything else falls back to the host's own file, warned once.
#   Second: the nomination is honoured ONLY when the repository root is
#   NOT a git working tree.  That is a VERIFIED
#   property, not a declared one, and it is the property that matters: a
#   tree git does not track cannot commit anything, and this pipeline's
#   entire integrity claim is about COMMITTED artifacts (R1, R3).  In a
#   real checkout `.git` is present, so the nomination is ignored and
#   said to be ignored, and the platform facts are the host's own with no
#   way around them.  Deleting `.git` to reach the nomination would leave
#   a record that can never be published, which is not a bypass but a
#   self-defeating act.
#
#   The answer is exported as PLAYTHROUGH_PLATFORM_SOURCE and printed in
#   the environment summary, so what a run believed about its platform is
#   part of its contract either way.
#   PURE ON PURPOSE: it prints and nothing else.  Every caller reaches it
#   through $(...), which is a subshell, so an export or a warn-once flag
#   set in here would die with that subshell -- which is exactly the
#   defect this function was written with the first time.
#   playthrough_check_platform does the exporting and the warning, in the
#   caller's own shell, where both stick.
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
        # A SYMLINK IS NOT EVIDENCE, even here.  The verdict is read a
        # moment after this resolves, and a link can be repointed in
        # between: what the gate then measures is not what was nominated.
        # `-f` alone would follow it, so this is checked before it.
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
#   Decide -- and by default REFUSE -- whether this host is still
#   receiving security fixes, because a version number is only as good
#   as the archive still publishing updates for it.
#
#   ImageMagick, ffmpeg and the Xorg/Xvfb stack all parse
#   untrusted-shaped input, and on an end-of-life release their known
#   issues stay unfixed by definition however current `dpkg-query`
#   looks.
#
#   THIS USED TO BE A WARNING, WITH THE HARD FAILURE OPT-IN VIA
#   PLAYTHROUGH_REQUIRE_SUPPORTED_PLATFORM=1.  That was the wrong way
#   round.  A warning is the correct shape for something an operator
#   might reasonably accept after reading it; this is a condition on the
#   whole toolchain that nobody reads a warning about in the middle of a
#   six-hundred-keystroke session, and the session's own record is
#   COMMITTED, so the consequence of getting it wrong is a permanent
#   artifact produced on an unmaintained parser stack with a note about
#   it in a log nobody re-reads.  An opt-in safeguard is a safeguard
#   that is off.
#
#   SO THE DEFAULT IS A REFUSAL, and it applies to BOTH unsupported
#   verdicts:
#
#     "no"          the table knows this release and it is past its
#                   end-of-life date.
#     "unverified"  the table does not know this release at all.  Also a
#                   refusal, because "cannot tell" is not "supported" --
#                   the table is deliberately small, so an operator on
#                   an untabulated release is the one who has to
#                   confirm support, and confirming it is what the
#                   waiver below records them doing.
#
#   THE WAIVER: PLAYTHROUGH_ALLOW_EOL_PLATFORM=<reason>
#
#   Set it to a NON-EMPTY REASON rather than to 1.  That is deliberate:
#   the reason is the only part a later reader of the evidence actually
#   needs, and a variable that has to be given a sentence cannot be set
#   by reflex.  The reason is warned once at run time, exported as
#   PLAYTHROUGH_PLATFORM_WAIVER, and printed in the environment summary
#   -- which is the record of what a session ran under -- so a film
#   recorded under a waiver says so in its own contract.
#
#   AND IT IS IN THE TRUST-BYPASS REGISTRY.  It was deliberately kept
#   out of it, on the argument that an end-of-life platform makes no
#   reading WRONG -- it raises the risk that a parser has an unfixed
#   defect, which needs hostile input to matter, and the only images this
#   pipeline decodes are PNGs it captured itself on a host that opens no
#   network connection -- so recording the waiver in the summary was
#   treated as sufficient.
#
#   A SECURITY REVIEW WAS RIGHT THAT THIS WAS THE WRONG CALL, and its
#   reasoning is the same reasoning this file already applies to every
#   other relaxable check: "a warning on stderr does not stop the very
#   next command from capturing a frame, committing it, and presenting it
#   as evidence".  Recording is not a control.  The specifics were also
#   concrete rather than theoretical -- ImageMagick's own advisory names
#   a heap-buffer-overflow in the X11 `import` command, which is this
#   pipeline's capture utility, for versions before 7.1.2-26; X.Org
#   published client-triggerable memory-safety fixes after the installed
#   Xvfb; and the distribution is marked vulnerable to an ffmpeg CVE.
#   Those are the three programs that photograph, decode and encode
#   every frame of the film.
#
#   So the waiver now forces the state to `diagnostic`, exactly like
#   every other entry, and the four stages that produce production media
#   refuse under it: launch_game.sh (the captured instance), capture.sh
#   (a kept frame), render_movie.py (the film) and embed_captions.sh (the
#   captioned film).  Diagnosis stays fully available -- capture.sh's
#   diagnostic mode withdraws its frame out of the working tree and never
#   exits 0 -- so a run on an out-of-support host can still be debugged;
#   it simply cannot manufacture evidence.  Reproducing the derivatives
#   on a supported, fully patched release is the remedy, and the residual
#   for anything that genuinely cannot be reproduced is recorded in
#   playthrough/TECHNICAL_NOTES.md rather than hidden.
#
#   COMMITTING IS DELIBERATELY NOT GATED ON IT.  Publishing artifacts
#   that already exist neither captures nor encodes anything, and gating
#   it would make an EOL host unable to commit the very disclosure that
#   records the residual -- a rule that destroys the evidence trail it
#   was meant to protect.
#
#   PLAYTHROUGH_REQUIRE_SUPPORTED_PLATFORM IS RETIRED, and it is
#   recognised rather than ignored: =1 is now the default and says so,
#   and =0 no longer weakens anything and says THAT, because an operator
#   who set a variable believing it configured something has to be told
#   it did not.
#
#   The table below is dated: end-of-life dates are facts about the
#   world, not about this repository, so it is small on purpose, states
#   when it was compiled, and treats anything it does not know as
#   unverified rather than as supported.

# playthrough_platform_waiver
#   The reason an out-of-support platform was accepted, or nothing.
#   Read at every call rather than memoised, because a caller may set it
#   after sourcing this file.
#
#   THE REASON IS UNTRUSTED TEXT, AND IT IS SANITISED HERE.  It is
#   written by a human, echoed into a warning, exported as
#   PLAYTHROUGH_PLATFORM_WAIVER and printed in the environment summary
#   that travels with a session's contract -- which is three places where
#   a newline forges a log line and an ANSI escape rewrites what a reader
#   sees.  So the value is reduced to printable ASCII on one line and
#   bounded in length: every control character, every escape introducer
#   and every newline becomes a single space, runs of spaces collapse, and
#   anything past the limit is dropped with an ellipsis.  A waiver whose
#   text was altered says so, once, rather than silently reading
#   differently from what was set.
#
#   IT MUST ALSO CONTAIN NO SECRET AND NO HOST-IDENTIFYING DETAIL.  There
#   is no way to check that mechanically, so it is documented here, in
#   the refusal message, and in the README: the reason is published
#   evidence, not a private note.
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
#   directory another local account may re-pave.  Returns 0 when both
#   roads are safe or the waiver is set, 1 when it refuses.
#
#   WHAT IT MEASURES, AND WHY A MODE CHECK ON THE DESTINATION IS NOT IT.
#   A security review found this tree checking the type, owner and mode of
#   every directory it wrote into, and of every ancestor BELOW its own
#   verified anchor -- and stopping there.  On a host whose /tmp is mode
#   2777 (world-writable and NOT sticky; measured on the provisioning
#   host, where a conventional /tmp is 1777) that leaves the road open:
#   in a world-writable non-sticky directory ANY account with write
#   permission may rename or unlink ANY entry regardless of who owns it,
#   so the anchor's own 0700 says nothing about whether the NAME will
#   still resolve to it at the next use.  Two roads matter, for two
#   different reasons:
#
#     * the RUNTIME anchor holds the X authority cookie -- a credential
#       that authenticates a client to the display being photographed --
#       plus the pid files, the locks and any in-flight journal;
#     * the REPOSITORY holds the evidence itself: the frames, the save,
#       the films, the ledgers.
#
#   THE ASYMMETRY IN WHAT CAN BE DONE ABOUT THEM IS THE REASON THIS IS A
#   REFUSAL WITH A WAIVER RATHER THAN EITHER A HARD ERROR OR A WARNING.
#   The runtime anchor is this pipeline's own choice and it moves itself
#   to a root-owned /run address when the conventional one is unsafe and
#   holds nothing (see THE ANCHOR IS CHOSEN, above).  The repository is
#   where the caller put it; nothing here can relocate a checkout, and a
#   hard error would make the pipeline unrunnable on a host it is
#   otherwise perfectly able to run on.  So the run REFUSES by default --
#   which is what a fail-closed control means -- and
#   PLAYTHROUGH_ALLOW_UNSAFE_PATH_ANCESTRY=<reason> proceeds, as a
#   registered TRUST BYPASS: setting it moves PLAYTHROUGH_TRUST_STATE to
#   diagnostic through the ordinary machinery, so a production capture is
#   refused and every report says why.
#
#   Called from playthrough_headless_up, beside playthrough_check_platform
#   and for the same reason: a launch is the moment evidence starts being
#   produced, and sourcing this file must stay inert.
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
    # The classification used to be cached in exported variables behind a
    # PLAYTHROUGH_PLATFORM_CHECKED flag, on the reasonable-sounding
    # grounds that /etc/os-release cannot change during a run.  But this
    # file is SOURCED into the caller's shell, so every one of those
    # variables was an INPUT as well as an output, and
    #
    #     PLAYTHROUGH_PLATFORM_CHECKED=1 PLAYTHROUGH_PLATFORM_SUPPORTED=yes
    #
    # made this function return 0 on an end-of-life host with no waiver,
    # no warning and PLAYTHROUGH_TRUST_STATE=trusted.  Measured, not
    # theorised.  That is a silent forgery of the very verdict the
    # trust-bypass registry now depends on, so the classification is
    # recomputed on every call and whatever the caller set is discarded:
    # these variables are outputs only.  The cost is one `sed` over a
    # small file and one `date` per call.
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
        # Compiled 2026-08-04 from the distributions' own published
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
        if [ -z "${eol}" ]; then
            export PLAYTHROUGH_PLATFORM_SUPPORTED="unverified"
        else
            local today
            today="$(date -u +%Y-%m-%d)"
            # Both sides are ISO-8601, so a lexical comparison is a date
            # comparison; a table entry of "2031-04" compares as
            # "2031-04" < "2031-04-01", which errs towards refusing
            # early rather than late.
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
    # Resolve the platform verdict so the record carries it.  Nothing in
    # it is memoised -- the classification is recomputed on every call so
    # that no inherited variable can forge it -- and a refusal is the
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
    # `|| true` because a refusal is the CALLER's business, not the
    # summary's: this function exists to record what a session ran
    # under, and a platform refusal that stopped the record from being
    # printed would destroy the one artifact that names the platform.
    # launch_game.sh and capture.sh call the same function and DO stop.
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
        # WHICH FILE the platform facts came from.  Normally
        # /etc/os-release; a harness may nominate another through
        # PLAYTHROUGH_OS_RELEASE to emulate a host it is not running on,
        # and that nomination is honoured only in a tree git does not
        # track (see playthrough_os_release_source).  So this line is
        # what says whether the verdict beside it is about THIS host, and
        # a verdict that came from elsewhere is still one the record
        # carries.  Printed ONCE: the summary's own test refuses a
        # repeated label, which is the signature of a copied line.
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
    # EVERY VALUE GOES THROUGH playthrough_redact, for the same reason
    # every diagnostic line does: this report is retained -- captured
    # into logs, quoted into reports, read by people who have no
    # business knowing where somebody else's clone lives -- and half of
    # these fields are absolute paths inside the checkout.  Printed
    # raw, PLAYTHROUGH_MANIFEST disclosed the full host path of the
    # working tree on every single line that named an artifact, which
    # is the same disclosure playthrough_log was fixed for.  Redaction
    # leaves paths OUTSIDE the checkout legible -- an interpreter under
    # /opt is a package location, not a per-operator one -- and reduces
    # the runtime scratch root to <runtime>, keeping the file name that
    # matters and dropping the location that does not.
    #
    # A PAIRWISE LOOP RATHER THAN ONE printf OVER THE WHOLE ARRAY,
    # because a substitution has to be applied per value; the field
    # list is still built as an array above, so the truncation hazard
    # the array exists to prevent is unchanged.
    #
    # THE STATUS OF EVERY printf IS KEPT, and that is load-bearing rather
    # than tidy.  A loop's own status is its condition's, so a printf
    # that failed inside one is swallowed -- and the direct run of this
    # file exists to PRINT the contract, so a summary that could not be
    # written is a failed run and has to say so.  A full disk or a
    # closed descriptor is exactly the case where a caller must not read
    # exit 0 as "the record landed".
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
