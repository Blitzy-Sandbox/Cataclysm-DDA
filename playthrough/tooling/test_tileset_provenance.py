#!/usr/bin/env python3
"""Regression suite for playthrough/tooling/tileset_provenance.py.

THE THING THIS MODULE GUARDS IS THE ONE INPUT GIT DOES NOT CARRY.
``gfx/`` is git-ignored (.gitignore:52) with four negations, and the
required MSXotto+ is not one of them -- so the artwork every frame of the
film is rendered in is untracked, and a tracked anchor stating its exact
bytes is the only thing that makes "the reviewed artwork" a checkable
claim.  A security review found the launcher accepting an installed
tileset on nothing but the ``NAME:`` line in its own ``tileset.txt``.

    python3 playthrough/tooling/test_tileset_provenance.py
    python3 -B -m unittest discover -s playthrough/tooling -p 'test_*.py'

WHAT IS ASSERTED
* THE COMPARISON IS SYMMETRIC.  A missing file, an extra file, a wrong
  digest and a wrong size are each a refusal.  An extra file is not
  harmless: the engine loads what the tileset's own JSON names, that JSON
  is itself anchored, and "extra artwork appeared" is the first half of a
  substitution.
* AN IN-PACK MANIFEST IS NOT AN ANCHOR.  The exploit is reproduced
  directly: alter a payload, regenerate ``SHA256SUMS`` over it, and the
  pack verifies itself perfectly while the tracked anchor refuses it.
* LINKS ARE REFUSED, NEVER FOLLOWED.  The install directory, any
  directory inside it, any file inside it, and the anchor itself.  A
  canonical path outside ``<repo>/gfx/`` is refused with both paths
  named.
* EVERY FAILURE TO READ IS A REFUSAL.  A missing anchor, an unparseable
  one, one from a future schema version, one whose own file list does not
  hash to its own tree digest, and a file that cannot be opened.
* THE RECIPE IS REPRODUCIBLE.  ``tree_digest`` is asserted against the
  digest computed by hand from its documented definition, and
  ``generate`` is asserted to round-trip through ``load_anchor``.

WHAT IS DELIBERATELY NOT ASSERTED
No test asserts the shipped anchor's digests as literals.  They change
legitimately the moment the artwork is re-composed from a newer upstream
commit, and a suite that hard-coded them would fail on a correct update
while proving nothing about the logic.  What IS asserted about the
shipped file is that it exists, that it validates under the module's own
rules, and that it describes the required tileset -- and, when the
artwork is actually installed on the host running the suite, that the
installation verifies against it.

Standard library only.  Nothing outside a temporary directory is
written.
"""

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tileset_provenance as provenance  # noqa: E402

TOOLING = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(TOOLING))

# The upstream block every generated document needs.  Fake values, named
# as fake: this suite asserts the SHAPE of provenance, and inventing a
# real-looking commit here would be the very thing the module refuses.
UPSTREAM = {
    "repo": "https://example.invalid/tilesets.git",
    "commit": "0" * 40,
    "committed": "2026-01-01T00:00:00+00:00",
    "subject": "a fixture anchor, not the shipped one",
    "path": "gfx/MShockXotto+",
}
RECIPE = "the fixture wrote these files directly"


class ProvenanceFixture(unittest.TestCase):
    """A sandbox checkout with one installed tileset."""

    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix="blitzy_provenance_")
        self.addCleanup(shutil.rmtree, self.directory, True)
        self.checkout = os.path.join(self.directory, "checkout")
        self.gfx = os.path.join(self.checkout, "gfx")
        self.tooling = os.path.join(self.checkout, "playthrough",
                                    "tooling")
        os.makedirs(self.tooling)
        self.install = os.path.join(self.gfx, "MShockXotto+")
        os.makedirs(self.install)
        self.write("tileset.txt",
                   "# a comment, as the shipped packs have\n"
                   "NAME: MshockXottoplus\nVIEW: MSXotto+\n")
        self.write("tiles.png", "the reviewed artwork\n")
        self.write("tile_config.json", "{}\n")
        self.anchor = os.path.join(self.tooling,
                                   "tileset_provenance.json")

    def write(self, name, text):
        """Write one file of the installed tileset."""
        path = os.path.join(self.install, name)
        parent = os.path.dirname(path)
        if not os.path.isdir(parent):
            os.makedirs(parent)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def seal(self, **overrides):
        """Anchor the installed tree exactly as it now stands."""
        document = provenance.generate(
            "gfx/MShockXotto+", UPSTREAM, RECIPE, root=self.checkout)
        document.update(overrides)
        provenance.write_anchor(document, self.anchor)
        return document

    def document(self):
        """Return the anchor on disk, parsed."""
        with open(self.anchor, encoding="utf-8") as handle:
            return json.load(handle)

    def rewrite(self, document):
        """Replace the anchor with ``document`` verbatim, valid or not."""
        with open(self.anchor, "w", encoding="utf-8") as handle:
            json.dump(document, handle)
        return self.anchor

    def verify(self, ident="MshockXottoplus", view="MSXotto+"):
        """Verify the sandbox install.  Raises on refusal."""
        return provenance.verify("gfx/MShockXotto+", ident, view,
                                 root=self.checkout)

    def refusal(self, ident="MshockXottoplus", view="MSXotto+"):
        """Return the refusal message, asserting that there is one."""
        with self.assertRaises(provenance.ProvenanceError) as caught:
            self.verify(ident, view)
        return str(caught.exception)


class TheTreeDigest(ProvenanceFixture):
    """The recipe, reproducible by hand from its own definition."""

    def test_it_is_the_documented_recipe_and_nothing_else(self):
        rows = provenance.scan_tree("gfx/MShockXotto+",
                                    root=self.checkout)
        text = "".join(
            "%s  %s\n" % (row["sha256"], row["path"])
            for row in sorted(
                rows, key=lambda row: row["path"].encode("utf-8")))
        self.assertEqual(
            provenance.tree_digest(rows),
            hashlib.sha256(text.encode("utf-8")).hexdigest())

    def test_the_order_is_byte_wise_and_not_the_input_order(self):
        rows = provenance.scan_tree("gfx/MShockXotto+",
                                    root=self.checkout)
        self.assertEqual(provenance.tree_digest(rows),
                         provenance.tree_digest(list(reversed(rows))))

    def test_one_changed_byte_changes_it(self):
        before = provenance.tree_digest(
            provenance.scan_tree("gfx/MShockXotto+",
                                 root=self.checkout))
        self.write("tiles.png", "the reviewed artwork!\n")
        after = provenance.tree_digest(
            provenance.scan_tree("gfx/MShockXotto+",
                                 root=self.checkout))
        self.assertNotEqual(before, after)

    def test_a_renamed_file_changes_it(self):
        """The path is hashed, not only the bytes."""
        before = provenance.tree_digest(
            provenance.scan_tree("gfx/MShockXotto+",
                                 root=self.checkout))
        os.rename(os.path.join(self.install, "tiles.png"),
                  os.path.join(self.install, "artwork.png"))
        after = provenance.tree_digest(
            provenance.scan_tree("gfx/MShockXotto+",
                                 root=self.checkout))
        self.assertNotEqual(before, after)


class TheHappyPath(ProvenanceFixture):
    """What a correctly provisioned checkout looks like."""

    def test_the_sealed_tree_verifies(self):
        sealed = self.seal()
        verified = self.verify()
        self.assertEqual(verified["tree_sha256"], sealed["tree_sha256"])
        self.assertEqual(verified["file_count"], 3)

    def test_a_nested_directory_is_walked(self):
        self.write(os.path.join("fonts", "extra.ttf"), "glyphs\n")
        self.seal()
        self.assertEqual(self.verify()["file_count"], 4)
        rows = provenance.scan_tree("gfx/MShockXotto+",
                                    root=self.checkout)
        self.assertIn("fonts/extra.ttf",
                      [row["path"] for row in rows])

    def test_the_id_and_view_are_read_from_the_tileset_txt(self):
        document = self.seal()
        self.assertEqual(document["tileset"]["id"], "MshockXottoplus")
        self.assertEqual(document["tileset"]["view"], "MSXotto+")
        self.assertEqual(document["tileset"]["directory"],
                         "gfx/MShockXotto+")

    def test_generate_round_trips_through_load_anchor(self):
        """The generator writes what the reader accepts, or neither is
        worth anything."""
        self.seal()
        loaded = provenance.load_anchor(self.anchor)
        self.assertEqual(loaded["file_count"], len(loaded["files"]))
        self.assertEqual(loaded["byte_count"],
                         sum(row["bytes"] for row in loaded["files"]))
        self.assertEqual(loaded["tree_sha256"],
                         provenance.tree_digest(loaded["files"]))

    def test_generating_twice_is_byte_identical(self):
        first = self.seal()
        second = provenance.generate(
            "gfx/MShockXotto+", UPSTREAM, RECIPE, root=self.checkout)
        self.assertEqual(json.dumps(first, sort_keys=True),
                         json.dumps(second, sort_keys=True))

    def test_an_absolute_directory_is_accepted_too(self):
        """launch_game.sh passes the absolute path it resolved."""
        self.seal()
        provenance.verify(self.install, "MshockXottoplus", "MSXotto+",
                          root=self.checkout)

    def test_a_trailing_separator_is_accepted(self):
        self.seal()
        provenance.verify(self.install + os.sep, root=self.checkout)


class TheSymmetricComparison(ProvenanceFixture):
    """A file the anchor does not name is as bad as one it cannot find."""

    def test_a_replaced_payload_is_refused_and_both_digests_named(self):
        """THE EXPLOIT: an in-pack manifest travels with the payload.

        Altering the artwork and regenerating SHA256SUMS over it leaves
        the pack verifying itself perfectly.  The tracked anchor is
        outside the thing it describes, so it refuses.
        """
        self.seal()
        self.write("tiles.png", "not the artwork that was reviewed\n")
        rows = []
        for name in sorted(os.listdir(self.install)):
            path = os.path.join(self.install, name)
            if not os.path.isfile(path) or name == "SHA256SUMS":
                continue
            with open(path, "rb") as handle:
                rows.append("%s  ./%s" % (
                    hashlib.sha256(handle.read()).hexdigest(), name))
        self.write("SHA256SUMS", "\n".join(rows) + "\n")
        message = self.refusal()
        self.assertIn("tiles.png", message)
        self.assertIn("hashes to", message)
        self.assertIn("the anchor names", message)

    def test_an_extra_file_is_refused(self):
        self.seal()
        self.write("surplus.png", "artwork nobody reviewed\n")
        self.assertIn("is installed and is NOT named by the anchor",
                      self.refusal())

    def test_a_missing_file_is_refused(self):
        self.seal()
        os.unlink(os.path.join(self.install, "tiles.png"))
        self.assertIn("is named by the anchor and is NOT installed",
                      self.refusal())

    def test_a_size_only_disagreement_is_refused(self):
        """Contrived on purpose: it can only come from a bad anchor."""
        self.seal()
        document = self.document()
        for row in document["files"]:
            if row["path"] == "tiles.png":
                row["bytes"] = row["bytes"] + 1
        document["byte_count"] += 1
        self.rewrite(document)
        self.assertIn("byte(s); the anchor names", self.refusal())

    def test_a_wrong_id_is_refused(self):
        self.seal()
        message = self.refusal(ident="SomebodyElsesTiles")
        self.assertIn("SomebodyElsesTiles", message)
        self.assertIn("MshockXottoplus", message)
        self.assertIn("TILES option", message)

    def test_a_wrong_view_is_refused(self):
        self.seal()
        self.assertIn("VIEW:", self.refusal(view="Somebody Else"))

    def test_an_anchor_for_another_directory_is_refused(self):
        self.seal()
        document = self.document()
        document["tileset"]["directory"] = "gfx/SomewhereElse"
        self.rewrite(document)
        self.assertIn("gfx/SomewhereElse", self.refusal())

    def test_a_wholly_replaced_tree_summarises_rather_than_floods(self):
        for index in range(30):
            self.write("sheet%02d.png" % index, "%d\n" % index)
        self.seal()
        for index in range(30):
            self.write("sheet%02d.png" % index, "replaced %d\n" % index)
        message = self.refusal()
        self.assertIn("further mismatch(es) not listed", message)
        self.assertLessEqual(
            message.count("hashes to"), provenance.PROBLEM_LIMIT,
            msg=("a refusal nobody reads to the end explains nothing, "
                 "so the list is bounded and the remainder counted"))

    def test_the_id_and_view_are_optional_arguments(self):
        """A caller that has not resolved them still gets the bytes
        checked."""
        self.seal()
        provenance.verify("gfx/MShockXotto+", root=self.checkout)


class LinksAreRefusedNeverFollowed(ProvenanceFixture):
    """Every place `[ -d ]` and `[ -f ]` used to dereference one."""

    def test_a_symlinked_install_directory_is_refused(self):
        self.seal()
        elsewhere = os.path.join(self.directory, "elsewhere")
        shutil.move(self.install, elsewhere)
        os.symlink(elsewhere, self.install)
        message = self.refusal()
        self.assertIn("is a symbolic link", message)
        self.assertIn("refused rather than followed", message)

    def test_a_symlinked_file_inside_is_refused(self):
        self.seal()
        os.symlink("/etc/passwd",
                   os.path.join(self.install, "sneaky.png"))
        self.assertIn("symbolic link", self.refusal())

    def test_a_symlinked_directory_inside_is_refused(self):
        self.seal()
        outside = os.path.join(self.directory, "outside")
        os.makedirs(outside)
        with open(os.path.join(outside, "x.png"), "w",
                  encoding="utf-8") as handle:
            handle.write("x\n")
        os.symlink(outside, os.path.join(self.install, "fonts"))
        self.assertIn("symbolic link", self.refusal())

    def test_a_fifo_inside_is_refused(self):
        """A device, socket or fifo has no business in artwork at all."""
        self.seal()
        os.mkfifo(os.path.join(self.install, "pipe.png"))
        self.assertIn("neither a directory nor a regular file",
                      self.refusal())

    def test_a_canonical_path_outside_gfx_is_refused(self):
        outside = os.path.join(self.directory, "outside-gfx")
        os.makedirs(outside)
        with self.assertRaises(provenance.ProvenanceError) as caught:
            provenance.approved_directory(outside, root=self.checkout)
        message = str(caught.exception)
        self.assertIn("canonicalises to", message)
        self.assertIn(os.path.join("gfx", "outside-gfx"), message)

    def test_a_symlinked_anchor_is_refused(self):
        """A link in its place redirects the trust root itself."""
        self.seal()
        elsewhere = os.path.join(self.directory, "somebody-elses.json")
        shutil.move(self.anchor, elsewhere)
        os.symlink(elsewhere, self.anchor)
        self.assertIn("redirects the trust root", self.refusal())

    def test_a_symlinked_tileset_txt_is_not_read(self):
        """The id would be read from somewhere unaccounted for."""
        elsewhere = os.path.join(self.directory, "elsewhere.txt")
        with open(elsewhere, "w", encoding="utf-8") as handle:
            handle.write("NAME: SomebodyElsesTiles\n")
        os.unlink(os.path.join(self.install, "tileset.txt"))
        os.symlink(elsewhere, os.path.join(self.install, "tileset.txt"))
        self.assertIsNone(
            provenance.tileset_field("gfx/MShockXotto+", "NAME",
                                     root=self.checkout))


class EveryFailureToReadIsARefusal(ProvenanceFixture):
    """Unestablished provenance is the finding, not a lesser outcome."""

    def test_a_missing_anchor_is_refused(self):
        message = self.refusal()
        self.assertIn("there is no tileset provenance anchor", message)
        self.assertIn("git-ignored", message)

    def test_an_unparseable_anchor_is_refused(self):
        self.seal()
        with open(self.anchor, "w", encoding="utf-8") as handle:
            handle.write("{ this is not json\n")
        self.assertIn("could not be read as JSON", self.refusal())

    def test_an_anchor_that_is_not_an_object_is_refused(self):
        self.seal()
        self.rewrite(["a list of nothing"])
        self.assertIn("not a JSON object", self.refusal())

    def test_a_future_schema_version_is_refused(self):
        self.seal()
        document = self.document()
        document["version"] = provenance.SCHEMA_VERSION + 1
        self.rewrite(document)
        message = self.refusal()
        self.assertIn("declares version", message)
        self.assertIn("read optimistically", message)

    def test_an_anchor_naming_no_files_is_refused(self):
        self.seal()
        document = self.document()
        document["files"] = []
        document["file_count"] = 0
        document["byte_count"] = 0
        self.rewrite(document)
        self.assertIn("names no files", self.refusal())

    def test_a_disagreeing_file_count_is_refused(self):
        self.seal()
        document = self.document()
        document["file_count"] = 99
        self.rewrite(document)
        self.assertIn("declares file_count", self.refusal())

    def test_a_disagreeing_byte_count_is_refused(self):
        self.seal()
        document = self.document()
        document["byte_count"] = 1
        self.rewrite(document)
        self.assertIn("declares byte_count", self.refusal())

    def test_an_internally_inconsistent_anchor_is_refused(self):
        self.seal()
        document = self.document()
        document["tree_sha256"] = "0" * 64
        self.rewrite(document)
        self.assertIn("internally inconsistent", self.refusal())

    def test_a_duplicate_path_is_refused(self):
        self.seal()
        document = self.document()
        document["files"].append(dict(document["files"][0]))
        document["file_count"] += 1
        document["byte_count"] += document["files"][0]["bytes"]
        self.rewrite(document)
        self.assertIn("twice", self.refusal())

    def test_a_truncated_digest_is_refused_where_it_is_read(self):
        self.seal()
        document = self.document()
        document["files"][0]["sha256"] = "abc123"
        self.rewrite(document)
        self.assertIn("64-character sha256", self.refusal())

    def test_an_uppercase_digest_is_refused(self):
        self.seal()
        document = self.document()
        document["files"][0]["sha256"] = "A" * 64
        self.rewrite(document)
        self.assertIn("lowercase hexadecimal", self.refusal())

    def test_an_absolute_anchored_path_is_refused(self):
        """Anchored paths are joined onto a directory and then read."""
        self.seal()
        document = self.document()
        document["files"][0]["path"] = "/etc/passwd"
        self.rewrite(document)
        self.assertIn("must be relative", self.refusal())

    def test_a_traversing_anchored_path_is_refused(self):
        self.seal()
        document = self.document()
        document["files"][0]["path"] = "../../etc/passwd"
        self.rewrite(document)
        self.assertIn("'..'", self.refusal())

    def test_a_missing_upstream_block_is_refused(self):
        self.seal()
        document = self.document()
        document.pop("upstream")
        self.rewrite(document)
        self.assertIn("no 'upstream' object", self.refusal())

    def test_a_missing_upstream_commit_is_refused(self):
        self.seal()
        document = self.document()
        document["upstream"]["commit"] = ""
        self.rewrite(document)
        self.assertIn("upstream.commit", self.refusal())

    def test_an_unreadable_file_is_refused(self):
        self.seal()
        target = os.path.join(self.install, "tiles.png")
        os.chmod(target, 0o000)
        self.addCleanup(os.chmod, target, 0o644)
        if os.access(target, os.R_OK):
            self.skipTest("running as a user that ignores file modes")
        self.assertIn("could not be read", self.refusal())

    def test_an_empty_install_is_refused(self):
        self.seal()
        for name in os.listdir(self.install):
            os.unlink(os.path.join(self.install, name))
        self.assertIn("holds no files at all", self.refusal())

    def test_a_generator_with_incomplete_provenance_is_refused(self):
        """A field nobody supplied is not a field to guess."""
        for field in provenance.ANCHOR_UPSTREAM_FIELDS:
            with self.subTest(field=field):
                partial = dict(UPSTREAM)
                partial[field] = ""
                with self.assertRaises(
                        provenance.ProvenanceError) as caught:
                    provenance.generate("gfx/MShockXotto+", partial,
                                        RECIPE, root=self.checkout)
                self.assertIn(field, str(caught.exception))
                self.assertIn("not a field to guess",
                              str(caught.exception))

    def test_a_tileset_txt_with_no_name_cannot_be_anchored(self):
        self.write("tileset.txt", "# no NAME here\nVIEW: MSXotto+\n")
        with self.assertRaises(provenance.ProvenanceError) as caught:
            provenance.generate("gfx/MShockXotto+", UPSTREAM, RECIPE,
                                root=self.checkout)
        self.assertIn("declares no NAME:", str(caught.exception))


class TheCommandLine(ProvenanceFixture):
    """The surface launch_game.sh actually calls."""

    def run_cli(self, *argv):
        """Run main() with stdout and stderr captured."""
        import io
        import contextlib
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            status = provenance.main(list(argv))
        return status, out.getvalue(), err.getvalue()

    def test_verify_reports_the_facts_on_stdout(self):
        sealed = self.seal()
        status, out, _ = self.run_cli(
            "--root", self.checkout, "verify",
            "--directory", "gfx/MShockXotto+",
            "--id", "MshockXottoplus", "--view", "MSXotto+")
        self.assertEqual(status, provenance.EXIT_OK)
        self.assertIn("TILESET_PROVENANCE=verified", out)
        self.assertIn("TILESET_PROVENANCE_TREE_SHA256=%s"
                      % sealed["tree_sha256"], out)
        self.assertIn("TILESET_PROVENANCE_UPSTREAM_COMMIT=%s"
                      % UPSTREAM["commit"], out)

    def test_a_refusal_exits_one_and_explains_itself_on_stderr(self):
        self.seal()
        self.write("tiles.png", "replaced\n")
        status, out, err = self.run_cli(
            "--root", self.checkout, "verify",
            "--directory", "gfx/MShockXotto+")
        self.assertEqual(status, provenance.EXIT_REFUSED)
        self.assertEqual(out, "")
        self.assertIn("FATAL", err)
        self.assertIn("tiles.png", err)

    def test_show_prints_the_anchor_summary(self):
        self.seal()
        status, out, _ = self.run_cli("--root", self.checkout, "show")
        self.assertEqual(status, provenance.EXIT_OK)
        for field in ("TILESET_PROVENANCE_ID=MshockXottoplus",
                      "TILESET_PROVENANCE_VIEW=MSXotto+",
                      "TILESET_PROVENANCE_DIRECTORY=gfx/MShockXotto+",
                      "TILESET_PROVENANCE_FILES=3"):
            self.assertIn(field, out)

    def test_show_refuses_when_there_is_nothing_to_show(self):
        status, _, err = self.run_cli("--root", self.checkout, "show")
        self.assertEqual(status, provenance.EXIT_REFUSED)
        self.assertIn("no tileset provenance anchor", err)

    def test_generate_writes_the_tracked_path_by_default(self):
        status, out, _ = self.run_cli(
            "--root", self.checkout, "generate",
            "--directory", "gfx/MShockXotto+",
            "--upstream-repo", UPSTREAM["repo"],
            "--upstream-commit", UPSTREAM["commit"],
            "--upstream-committed", UPSTREAM["committed"],
            "--upstream-path", UPSTREAM["path"],
            "--composed-with", RECIPE)
        self.assertEqual(status, provenance.EXIT_OK)
        self.assertIn("TILESET_PROVENANCE_WRITTEN=%s" % self.anchor, out)
        self.assertEqual(self.verify()["tileset"]["id"],
                         "MshockXottoplus")

    def test_the_anchor_path_is_derived_and_not_a_tunable(self):
        """An anchor a caller can point elsewhere is not an anchor."""
        self.assertEqual(
            provenance.anchor_path(self.checkout),
            os.path.join(self.checkout, "playthrough", "tooling",
                         "tileset_provenance.json"))
        with open(os.path.join(TOOLING, "tileset_provenance.py"),
                  encoding="utf-8") as handle:
            source = handle.read()
        self.assertNotIn(
            "os.environ", source,
            msg=("the anchor's location and every rule about it are "
                 "constants: nothing in this module may be relaxed by "
                 "an environment variable"))


class TheShippedAnchor(unittest.TestCase):
    """The repository's own file, held to the module's own rules."""

    def setUp(self):
        self.path = os.path.join(TOOLING, "tileset_provenance.json")

    def test_it_exists_and_validates(self):
        document = provenance.load_anchor(self.path)
        self.assertEqual(document["version"],
                         provenance.SCHEMA_VERSION)
        self.assertGreater(document["file_count"], 1)
        self.assertGreater(document["byte_count"], 0)

    def test_it_describes_the_required_tileset(self):
        document = provenance.load_anchor(self.path)
        self.assertEqual(document["tileset"]["id"], "MshockXottoplus")
        self.assertEqual(document["tileset"]["view"], "MSXotto+")
        self.assertEqual(document["tileset"]["directory"],
                         "gfx/MShockXotto+")

    def test_it_names_an_exact_upstream_commit(self):
        """A tag or a branch would move; a commit does not."""
        upstream = provenance.load_anchor(self.path)["upstream"]
        self.assertIn("I-am-Erk/CDDA-Tilesets", upstream["repo"])
        self.assertEqual(len(upstream["commit"]), 40)
        self.assertTrue(
            set(upstream["commit"]) <= provenance.SHA256_ALPHABET)
        self.assertIn("T", upstream["committed"])
        self.assertEqual(upstream["path"], "gfx/MShockXotto+")

    def test_it_records_how_the_tree_was_composed(self):
        document = provenance.load_anchor(self.path)
        self.assertIn("compose.py", document["composed_with"])
        self.assertIn("SHA256SUMS", document["in_pack_manifest"])
        self.assertIn("sha256", document["tree_sha256_recipe"])

    def test_it_names_the_files_the_engine_actually_loads(self):
        named = {row["path"]
                 for row in provenance.load_anchor(self.path)["files"]}
        for required in ("tileset.txt", "tile_config.json", "tiles.png",
                         "fallback.png"):
            self.assertIn(required, named)

    def test_the_installed_artwork_verifies_against_it(self):
        """Skipped only where the artwork is not installed at all.

        gfx/ is git-ignored, so a fresh checkout legitimately has no
        MSXotto+ yet -- but where it IS installed, the shipped anchor is
        the statement it has to satisfy, and this is the assertion the
        launcher makes on every launch.
        """
        installed = os.path.join(REPO, "gfx", "MShockXotto+")
        if not os.path.isdir(installed):
            self.skipTest("MSXotto+ is not installed in this checkout")
        document = provenance.verify(
            "gfx/MShockXotto+", "MshockXottoplus", "MSXotto+", root=REPO)
        self.assertEqual(
            document["tree_sha256"],
            provenance.tree_digest(provenance.scan_tree(
                "gfx/MShockXotto+", root=REPO)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
