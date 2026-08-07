#!/usr/bin/env python3
"""Verify the installed tileset against a TRACKED external anchor.

WHY THIS MODULE EXISTS, IN ONE SENTENCE.  ``gfx/`` is git-ignored
[.gitignore:52] with only four negations, so the artwork the whole film
is rendered in -- MSXotto+, which is NOT one of those four -- is the one
substantive input to this pipeline that git does not carry, and until
this module existed nothing said which bytes it had to be.

WHAT WAS WRONG.  ``launch_game.sh`` accepted an installed ``gfx/*``
directory on the strength of the ``NAME:`` or ``VIEW:`` line in its own
``tileset.txt``, with no provenance check at all: the whole verification
path (``verify_pack_provenance``) ran only when a tileset was INGESTED
from a staged pack, and an already-installed one -- the normal case on a
provisioned host -- went straight to being used.  Three consequences,
each reproduced before this was written:

  * a payload file replaced with anything at all was accepted, because
    the only integrity manifest was the pack's own in-tree
    ``SHA256SUMS``.  A manifest that travels inside the payload is not an
    anchor: an attacker who can write the artwork can write the list of
    its digests in the same breath, and regenerating it takes one
    command.  Measured: modified ``tiles.png`` plus a regenerated
    ``SHA256SUMS``, accepted, exit 0, ``origin=required-installed``.
  * ``gfx/MShockXotto+`` replaced by a SYMLINK to a directory outside
    the checkout was accepted, because ``[ -d ]`` and ``[ -f ]`` follow
    links.  Measured: accepted, exit 0.
  * nothing anywhere named the upstream commit the artwork came from, so
    "the reviewed artwork" was not a checkable claim in either
    direction.

WHAT IS ENFORCED NOW.  ``playthrough/tooling/tileset_provenance.json``
is a TRACKED anchor -- so its own integrity is git's, the same trust
root as every script in this tree -- and it states the upstream
repository and exact commit, the compose recipe, the tileset's id and
view, and the size and SHA-256 of EVERY file of the composed tree plus a
digest over that whole ordered list.  ``launch_game.sh`` calls this
module before the resolved tileset is used, on every launch, and a
mismatch of any kind stops the run:

  * the anchor is missing, a symlink, unreadable or malformed;
  * the declared id or view is not the anchored one;
  * the install directory is a symlink, contains a symlink or a special
    file, or canonicalises outside ``<repo>/gfx/``;
  * a file the anchor names is absent, the wrong size or the wrong
    digest;
  * a file exists that the anchor does not name;
  * the recomputed tree digest is not the anchored one.

FAIL CLOSED, ALWAYS.  Every failure to READ something is a refusal, not
a pass: an anchor that cannot be parsed, a file that cannot be hashed
and a directory that cannot be walked all mean the same thing here --
the provenance of the artwork is unestablished, and an unestablished
provenance is exactly what this module exists to stop.

THE IN-PACK MANIFEST IS KEPT, AND DEMOTED.  ``SHA256SUMS`` inside the
pack is still verified on ingestion by ``verify_pack_provenance``, where
it does catch a corrupted copy.  It is no longer treated as the anchor,
because it cannot be one.

    playthrough/tooling/tileset_provenance.py verify \\
        --directory gfx/MShockXotto+ --id MshockXottoplus \\
        --view MSXotto+
    playthrough/tooling/tileset_provenance.py generate \\
        --directory gfx/MShockXotto+ \\
        --upstream-repo https://github.com/I-am-Erk/CDDA-Tilesets.git \\
        --upstream-commit <sha> --upstream-committed <iso8601> \\
        --upstream-subject <subject>
    playthrough/tooling/tileset_provenance.py show

``generate`` exists so the anchor is REPRODUCIBLE from the repository
rather than being a file of unexplained digests: re-composing the same
upstream commit with the same recipe and regenerating must produce the
same document, and if it does not, that difference is the finding.

Standard library only.  No subprocess, no network, no shell.
"""

import argparse
import hashlib
import json
import os
import sys

# The anchor's location, relative to the repository root.  A CONSTANT
# rather than a tunable: an anchor a caller can point elsewhere is not
# an anchor, and the whole value of this file is that it is the tracked
# one.  Tests exercise the real path inside their own sandbox checkout.
ANCHOR_REL_PARTS = ("playthrough", "tooling", "tileset_provenance.json")

# Where a tileset may live.  The engine resolves ``gfx/`` relative to the
# working directory [src/path_info.cpp:134-137], and the launcher runs
# from the repository root, so this is the only directory an installed
# tileset can occupy.
GFX_DIR_NAME = "gfx"

# The schema this module writes and the only one it accepts.  A document
# from the future is refused rather than read optimistically.
SCHEMA_VERSION = 1

# The anchor's required shape, checked field by field before any digest
# is computed.  A malformed anchor is a refusal: a check that silently
# skipped the part of the document it could not understand would report
# success for artwork it had not verified.
ANCHOR_TILESET_FIELDS = ("id", "view", "directory")
ANCHOR_UPSTREAM_FIELDS = ("repo", "commit", "committed", "path")
ANCHOR_FILE_FIELDS = ("path", "bytes", "sha256")

# 64 lowercase hex characters, and nothing else, so a truncated or
# uppercase digest is caught where it is read rather than where it fails
# to match.
SHA256_LENGTH = 64
SHA256_ALPHABET = frozenset("0123456789abcdef")

# How many individual mismatches a refusal lists before it summarises.
# A wholly replaced tree would otherwise print one line per file, and a
# refusal nobody reads to the end is a refusal that explains nothing.
PROBLEM_LIMIT = 10

# Read in fixed blocks so a large sheet -- ``tiles.png`` is nearly 3 MB
# and ``fallback.png`` another 316 kB -- is hashed without being held in
# memory whole.
READ_BLOCK = 1 << 20


class ProvenanceError(Exception):
    """The provenance of the installed artwork is not established.

    Raised for every failure, including every failure to READ: this
    module has one answer for "the anchor says otherwise" and "the
    anchor could not be consulted", because both leave the artwork
    unverified.
    """


def anchor_path(root=None):
    """Return the tracked anchor's absolute path under ``root``."""
    base = os.path.abspath(root if root else os.getcwd())
    return os.path.join(base, *ANCHOR_REL_PARTS)


def _assert_hex_digest(value, what):
    """Return ``value`` if it is a full lowercase sha256, or raise."""
    if not isinstance(value, str) or len(value) != SHA256_LENGTH:
        raise ProvenanceError(
            "%s is not a 64-character sha256 digest: %r" % (what, value))
    if not set(value) <= SHA256_ALPHABET:
        raise ProvenanceError(
            "%s is not lowercase hexadecimal: %r" % (what, value))
    return value


def _assert_relative(path, what):
    """Return ``path`` if it is a safe relative path, or raise.

    Anchored paths are joined onto a directory this module then reads, so
    an absolute path, a parent traversal or a backslash-separated
    Windows path in the anchor would be a read outside the tree the
    anchor claims to describe.
    """
    if not isinstance(path, str) or not path:
        raise ProvenanceError("%s is not a path: %r" % (what, path))
    if path.startswith("/") or "\\" in path or os.path.isabs(path):
        raise ProvenanceError(
            "%s must be relative to the tileset directory and must not "
            "be a Windows path: %r" % (what, path))
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ProvenanceError(
            "%s must not contain an empty, '.' or '..' component: %r"
            % (what, path))
    return path


def load_anchor(path):
    """Read and fully validate the anchor at ``path``.

    Every field is checked before a single byte of artwork is hashed,
    because a document this module only half understood would produce a
    verdict about only half the tree while reporting success.

    The file must be a REGULAR file and must not be a symlink.  A
    symlinked anchor is a redirection of the trust root itself: the
    tracked path would be present and the bytes consulted would be
    somebody else's.
    """
    if os.path.islink(path):
        raise ProvenanceError(
            "the tileset provenance anchor '%s' is a symbolic link.  "
            "The anchor is the tracked statement of which artwork is "
            "permitted, so a link in its place redirects the trust root "
            "itself; restore the file git carries" % path)
    if not os.path.isfile(path):
        raise ProvenanceError(
            "there is no tileset provenance anchor at '%s'.  The "
            "artwork under gfx/ is git-ignored, so this tracked file is "
            "the only statement of which bytes it must be, and a run "
            "that cannot consult it has not verified the artwork it is "
            "about to render" % path)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, ValueError) as error:
        raise ProvenanceError(
            "the tileset provenance anchor '%s' could not be read as "
            "JSON: %s" % (path, error))
    if not isinstance(document, dict):
        raise ProvenanceError(
            "the tileset provenance anchor '%s' is not a JSON object"
            % path)
    version = document.get("version")
    if version != SCHEMA_VERSION:
        raise ProvenanceError(
            "the tileset provenance anchor '%s' declares version %r; "
            "this module reads version %d only, and a document it does "
            "not understand is refused rather than read optimistically"
            % (path, version, SCHEMA_VERSION))
    for name, fields in (("tileset", ANCHOR_TILESET_FIELDS),
                         ("upstream", ANCHOR_UPSTREAM_FIELDS)):
        block = document.get(name)
        if not isinstance(block, dict):
            raise ProvenanceError(
                "the tileset provenance anchor '%s' has no %r object"
                % (path, name))
        for field in fields:
            value = block.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ProvenanceError(
                    "the tileset provenance anchor '%s' has no %s.%s"
                    % (path, name, field))
    _assert_relative(document["tileset"]["directory"],
                     "tileset.directory")
    _assert_hex_digest(document.get("tree_sha256"), "tree_sha256")
    rows = document.get("files")
    if not isinstance(rows, list) or not rows:
        raise ProvenanceError(
            "the tileset provenance anchor '%s' names no files.  An "
            "anchor that describes an empty tree would verify an empty "
            "tree" % path)
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ProvenanceError(
                "the tileset provenance anchor '%s' has a files entry "
                "that is not an object" % path)
        for field in ANCHOR_FILE_FIELDS:
            if field not in row:
                raise ProvenanceError(
                    "a files entry of '%s' has no %r" % (path, field))
        _assert_relative(row["path"], "files[].path")
        _assert_hex_digest(row["sha256"], "the digest of %r"
                           % row["path"])
        if not isinstance(row["bytes"], int) or row["bytes"] < 0:
            raise ProvenanceError(
                "the anchored size of %r is not a byte count: %r"
                % (row["path"], row["bytes"]))
        if row["path"] in seen:
            raise ProvenanceError(
                "the tileset provenance anchor '%s' names %r twice"
                % (path, row["path"]))
        seen.add(row["path"])
    count = document.get("file_count")
    if count != len(rows):
        raise ProvenanceError(
            "the tileset provenance anchor '%s' declares file_count %r "
            "but names %d files" % (path, count, len(rows)))
    total = document.get("byte_count")
    measured = sum(row["bytes"] for row in rows)
    if total != measured:
        raise ProvenanceError(
            "the tileset provenance anchor '%s' declares byte_count %r "
            "but its own entries sum to %d" % (path, total, measured))
    recomputed = tree_digest(rows)
    if recomputed != document["tree_sha256"]:
        raise ProvenanceError(
            "the tileset provenance anchor '%s' declares tree_sha256 %s "
            "but its own file list hashes to %s, so the document is "
            "internally inconsistent and cannot be trusted to describe "
            "anything" % (path, document["tree_sha256"], recomputed))
    return document


def tree_digest(rows):
    """Return the anchored digest over an ordered file list.

    THE RECIPE, stated once and implemented once: sha256 over the
    concatenation of ``"<sha256>  <path>\\n"`` for every regular file,
    ordered by byte-wise ascending path, paths relative to the tileset
    directory with no ``./`` prefix.  It is the same shape ``sha256sum``
    prints, so the value can be reproduced by hand, and the ordering is
    byte-wise rather than locale-dependent because a digest that changed
    with ``$LC_ALL`` would be no digest at all.
    """
    ordered = sorted(rows, key=lambda row: row["path"].encode("utf-8"))
    text = "".join("%s  %s\n" % (row["sha256"], row["path"])
                   for row in ordered)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _digest_file(path):
    """Return one file's sha256 and size, or raise.

    A file that cannot be read is a refusal.  The artwork is being
    verified because it decides what the film looks like; "I could not
    check this one" is not a state this module has an answer for.
    """
    total = 0
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            while True:
                block = handle.read(READ_BLOCK)
                if not block:
                    break
                total += len(block)
                digest.update(block)
    except OSError as error:
        raise ProvenanceError(
            "'%s' could not be read while verifying the installed "
            "tileset: %s" % (path, error))
    return digest.hexdigest(), total


def approved_directory(directory, root=None):
    """Return the canonical install path, or raise.

    THE CONFINEMENT, and the answer to ``[ -d ]`` and ``[ -f ]``
    following links.  The directory itself must not be a symlink, every
    component of the path must be a real directory, and the canonical
    result must be exactly ``<root>/gfx/<name>``.  A link is refused
    rather than dereferenced: artwork that lives outside the checkout is
    outside everything this repository can say about it, and the run
    would render it while every other check passed.
    """
    base = os.path.abspath(root if root else os.getcwd())
    given = os.path.join(base, directory) if not os.path.isabs(
        directory) else directory
    given = given.rstrip(os.sep) or os.sep
    if os.path.islink(given):
        raise ProvenanceError(
            "the installed tileset '%s' is a symbolic link.  Artwork "
            "reached through a link is not artwork this checkout can "
            "account for -- the link's target can be replaced without "
            "anything under gfx/ changing -- so it is refused rather "
            "than followed" % given)
    if not os.path.isdir(given):
        raise ProvenanceError(
            "the installed tileset '%s' is not a directory" % given)
    canonical = os.path.realpath(given)
    expected = os.path.join(os.path.realpath(base), GFX_DIR_NAME,
                            os.path.basename(given))
    if canonical != expected:
        raise ProvenanceError(
            "the installed tileset '%s' canonicalises to '%s', which is "
            "not '%s'.  A tileset is loaded from gfx/ inside this "
            "checkout [src/path_info.cpp:134-137] and from nowhere "
            "else" % (given, canonical, expected))
    return canonical


def scan_tree(directory, root=None):
    """Return every regular file of an install, digested.

    Rows are ``{"path", "bytes", "sha256"}`` with paths relative to the
    tileset directory, exactly as the anchor records them.

    A SYMBOLIC LINK OR A SPECIAL FILE ANYWHERE INSIDE IS A REFUSAL, not
    an entry to skip and not one to follow.  A link inside the tree reads
    (or writes) somewhere else the moment the engine opens it, and a
    device, socket or fifo has no business in an artwork pack at all --
    the same rule ``verify_pack_provenance`` applies on ingestion,
    applied again to what actually landed.
    """
    canonical = approved_directory(directory, root)
    rows = []
    for base, names, files in os.walk(canonical, followlinks=False):
        names.sort()
        for name in sorted(names):
            path = os.path.join(base, name)
            if os.path.islink(path):
                raise ProvenanceError(
                    "'%s' inside the installed tileset is a symbolic "
                    "link to a directory; the tree is refused rather "
                    "than walked through it" % path)
        for name in sorted(files):
            path = os.path.join(base, name)
            if os.path.islink(path):
                raise ProvenanceError(
                    "'%s' inside the installed tileset is a symbolic "
                    "link.  An artwork tree is directories and regular "
                    "files only; a link resolves somewhere else once "
                    "the engine opens it" % path)
            if not os.path.isfile(path):
                raise ProvenanceError(
                    "'%s' inside the installed tileset is neither a "
                    "directory nor a regular file" % path)
            digest, size = _digest_file(path)
            rows.append({
                "path": os.path.relpath(path, canonical),
                "bytes": size,
                "sha256": digest,
            })
    if not rows:
        raise ProvenanceError(
            "the installed tileset '%s' holds no files at all"
            % canonical)
    rows.sort(key=lambda row: row["path"].encode("utf-8"))
    return rows


def _bounded(problems):
    """Return at most PROBLEM_LIMIT problems plus a count of the rest."""
    if len(problems) <= PROBLEM_LIMIT:
        return tuple(problems)
    remainder = len(problems) - PROBLEM_LIMIT
    return tuple(problems[:PROBLEM_LIMIT]) + (
        "and %d further mismatch(es) not listed; the installed tree "
        "does not correspond to the anchored one at all" % remainder,)


def compare(anchor, rows, declared_id=None, declared_view=None,
            directory=None):
    """Return every way ``rows`` disagrees with ``anchor``.

    An EMPTY tuple means verified.  The comparison is symmetric on
    purpose: a file the anchor does not name is as much a failure as one
    it names and cannot find.  An extra file is not harmless -- the
    engine loads what the tileset's own JSON tells it to, that JSON is
    itself one of the anchored files, and "extra artwork appeared" is
    indistinguishable from the first half of a substitution.
    """
    problems = []
    tileset = anchor["tileset"]
    if declared_id is not None and declared_id != tileset["id"]:
        problems.append(
            "the installed tileset declares NAME: %r but the anchor "
            "describes %r.  The id decides what seed_options.py writes "
            "to the TILES option, so a run under a different one is a "
            "run in different artwork" % (declared_id, tileset["id"]))
    if declared_view is not None and declared_view != tileset["view"]:
        problems.append(
            "the installed tileset declares VIEW: %r but the anchor "
            "describes %r" % (declared_view, tileset["view"]))
    if directory is not None:
        expected = tileset["directory"].rstrip("/")
        given = "%s/%s" % (GFX_DIR_NAME, os.path.basename(
            directory.rstrip(os.sep)))
        if given != expected:
            problems.append(
                "the tileset is installed at %r but the anchor "
                "describes %r" % (given, expected))
    anchored = {row["path"]: row for row in anchor["files"]}
    installed = {row["path"]: row for row in rows}
    for path in sorted(set(anchored) - set(installed)):
        problems.append(
            "%r is named by the anchor and is NOT installed" % path)
    for path in sorted(set(installed) - set(anchored)):
        problems.append(
            "%r is installed and is NOT named by the anchor" % path)
    for path in sorted(set(anchored) & set(installed)):
        want = anchored[path]
        got = installed[path]
        if got["sha256"] != want["sha256"]:
            problems.append(
                "%r hashes to %s; the anchor names %s"
                % (path, got["sha256"], want["sha256"]))
        elif got["bytes"] != want["bytes"]:
            problems.append(
                "%r is %d byte(s); the anchor names %d"
                % (path, got["bytes"], want["bytes"]))
    if not problems:
        measured = tree_digest(rows)
        if measured != anchor["tree_sha256"]:
            problems.append(
                "every file matched individually but the tree hashes to "
                "%s rather than the anchored %s, which can only mean the "
                "comparison itself is wrong; nothing is accepted on that "
                "basis" % (measured, anchor["tree_sha256"]))
    return _bounded(problems)


def verify(directory, declared_id=None, declared_view=None, root=None,
           anchor=None):
    """Verify an installed tileset.  Return the anchor, or raise.

    The one entry point ``launch_game.sh`` calls.  It raises
    :class:`ProvenanceError` for every negative outcome -- including
    every failure to read -- so a caller has exactly two states to
    handle and neither of them is "probably fine".
    """
    document = load_anchor(anchor if anchor else anchor_path(root))
    rows = scan_tree(directory, root)
    problems = compare(document, rows, declared_id, declared_view,
                       directory)
    if problems:
        raise ProvenanceError(
            "the installed tileset does not match the tracked "
            "provenance anchor:\n  - %s" % "\n  - ".join(problems))
    return document


def tileset_field(directory, field, root=None):
    """Return one field of an installed tileset.txt, or ``None``.

    The engine's own reader trims the value and tolerates a trailing
    carriage return in a pack authored on Windows, so this does too --
    and ``launch_game.sh`` reads the same two fields the same way, which
    is why a run cannot resolve one id and verify another.
    """
    canonical = approved_directory(directory, root)
    path = os.path.join(canonical, "tileset.txt")
    if not os.path.isfile(path) or os.path.islink(path):
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                stripped = line.strip()
                if stripped.startswith("%s:" % field):
                    return stripped.split(":", 1)[1].strip()
    except OSError as error:
        raise ProvenanceError(
            "'%s' could not be read: %s" % (path, error))
    return None


def generate(directory, upstream, composed_with, root=None,
             in_pack_manifest="SHA256SUMS"):
    """Build the anchor document for an installed tileset.

    Here so the anchor is REPRODUCIBLE rather than a file of
    unexplained digests: re-composing the same upstream commit with the
    recipe recorded in ``composed_with`` and regenerating must produce
    this same document, byte for byte, and a difference is itself the
    finding.

    ``upstream`` must carry every field the schema requires; a generator
    that filled a missing one with a plausible default would be
    inventing provenance, which is the opposite of the point.
    """
    missing = [name for name in ANCHOR_UPSTREAM_FIELDS
               if not str(upstream.get(name, "")).strip()]
    if missing:
        raise ProvenanceError(
            "the upstream provenance is incomplete: %s.  An anchor "
            "states where the artwork came from; a field nobody supplied "
            "is not a field to guess" % ", ".join(sorted(missing)))
    canonical = approved_directory(directory, root)
    rows = scan_tree(canonical, root)
    name = os.path.basename(canonical)
    ident = tileset_field(canonical, "NAME", root)
    view = tileset_field(canonical, "VIEW", root)
    if not ident:
        raise ProvenanceError(
            "'%s/tileset.txt' declares no NAME:, so there is no id to "
            "anchor" % canonical)
    document = {
        "version": SCHEMA_VERSION,
        "purpose": (
            "The EXTERNAL trust anchor for the required tileset.  gfx/ "
            "is git-ignored (.gitignore:52), so the artwork the film is "
            "rendered in is the one untracked input to the whole "
            "pipeline: this file is the tracked statement of exactly "
            "which bytes it must be.  launch_game.sh verifies the "
            "COMPLETE installed tree against it before the tileset is "
            "used, on every launch."),
        "tileset": {
            "id": ident,
            "view": view or "",
            "directory": "%s/%s" % (GFX_DIR_NAME, name),
        },
        "upstream": {field: str(upstream[field]).strip()
                     for field in ("repo", "commit", "committed",
                                   "subject", "path")
                     if field in upstream},
        "composed_with": composed_with,
        "in_pack_manifest": in_pack_manifest,
        "tree_sha256_recipe": (
            "sha256 over the concatenation of '<sha256>  <path>\\n' for "
            "every regular file in the tree, ordered by byte-wise "
            "ascending path (LC_ALL=C sort), paths relative to the "
            "tileset directory with no './' prefix"),
        "tree_sha256": tree_digest(rows),
        "file_count": len(rows),
        "byte_count": sum(row["bytes"] for row in rows),
        "files": rows,
    }
    return document


def write_anchor(document, path):
    """Write an anchor document, formatted as the tracked one is."""
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2, sort_keys=False)
        handle.write("\n")
    return path


EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_USAGE = 2


def _parser():
    """Build the command line."""
    parser = argparse.ArgumentParser(
        description="Verify the installed tileset against the tracked "
                    "provenance anchor.")
    parser.add_argument(
        "--root", default=None,
        help="repository root; defaults to the working directory")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser(
        "verify", help="verify an installed tileset (exit 1 if it does "
                       "not match)")
    check.add_argument("--directory", required=True,
                       help="the installed tileset, e.g. "
                            "gfx/MShockXotto+")
    check.add_argument("--id", default=None, dest="ident",
                       help="the id the caller resolved, checked "
                            "against the anchor")
    check.add_argument("--view", default=None,
                       help="the view label the caller resolved")

    make = sub.add_parser(
        "generate", help="regenerate the anchor from an installed tree")
    make.add_argument("--directory", required=True)
    make.add_argument("--upstream-repo", required=True)
    make.add_argument("--upstream-commit", required=True)
    make.add_argument("--upstream-committed", required=True)
    make.add_argument("--upstream-subject", default="")
    make.add_argument("--upstream-path", required=True)
    make.add_argument("--composed-with", required=True)
    make.add_argument("--output", default=None,
                      help="where to write; defaults to the tracked "
                           "anchor path")

    sub.add_parser("show", help="print the anchor's summary")
    return parser


def main(argv=None):
    """Run the command line.  Returns a process exit status."""
    args = _parser().parse_args(argv)
    try:
        if args.command == "verify":
            document = verify(args.directory, args.ident, args.view,
                              args.root)
            sys.stdout.write("TILESET_PROVENANCE=verified\n")
            sys.stdout.write("TILESET_PROVENANCE_TREE_SHA256=%s\n"
                             % document["tree_sha256"])
            sys.stdout.write("TILESET_PROVENANCE_FILES=%d\n"
                             % document["file_count"])
            sys.stdout.write("TILESET_PROVENANCE_UPSTREAM_COMMIT=%s\n"
                             % document["upstream"]["commit"])
            return EXIT_OK
        if args.command == "generate":
            document = generate(
                args.directory,
                {"repo": args.upstream_repo,
                 "commit": args.upstream_commit,
                 "committed": args.upstream_committed,
                 "subject": args.upstream_subject,
                 "path": args.upstream_path},
                args.composed_with, args.root)
            destination = args.output or anchor_path(args.root)
            write_anchor(document, destination)
            sys.stdout.write("TILESET_PROVENANCE_WRITTEN=%s\n"
                             % destination)
            sys.stdout.write("TILESET_PROVENANCE_TREE_SHA256=%s\n"
                             % document["tree_sha256"])
            return EXIT_OK
        document = load_anchor(anchor_path(args.root))
        sys.stdout.write("TILESET_PROVENANCE_ID=%s\n"
                         % document["tileset"]["id"])
        sys.stdout.write("TILESET_PROVENANCE_VIEW=%s\n"
                         % document["tileset"]["view"])
        sys.stdout.write("TILESET_PROVENANCE_DIRECTORY=%s\n"
                         % document["tileset"]["directory"])
        sys.stdout.write("TILESET_PROVENANCE_UPSTREAM_COMMIT=%s\n"
                         % document["upstream"]["commit"])
        sys.stdout.write("TILESET_PROVENANCE_TREE_SHA256=%s\n"
                         % document["tree_sha256"])
        sys.stdout.write("TILESET_PROVENANCE_FILES=%d\n"
                         % document["file_count"])
        sys.stdout.write("TILESET_PROVENANCE_BYTES=%d\n"
                         % document["byte_count"])
        return EXIT_OK
    except ProvenanceError as error:
        sys.stderr.write("playthrough: FATAL: %s\n" % error)
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
