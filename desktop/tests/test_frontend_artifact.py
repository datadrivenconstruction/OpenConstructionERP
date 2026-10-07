# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The next job must consume the exact tested frontend and paired sidecar."""

import importlib.util
import hashlib
import json
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("frontend_artifact", Path(__file__).parents[1] / "frontend_artifact.py")
artifact = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(artifact)


class FrontendArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.dist = self.root / "dist"
        self.dist.mkdir()
        (self.dist / "assets").mkdir()
        (self.dist / "index.html").write_text("<script src='assets/app.js'></script>", encoding="utf-8")
        (self.dist / "splash.html").write_text("function failStage(){}", encoding="utf-8")
        (self.dist / "assets/app.js").write_bytes(b"console.log('tested');")
        (self.dist / ".hidden").write_bytes(b"kept")
        self.sidecar = self.root / "sidecar.exe"
        self.sidecar.write_bytes(b"tested-sidecar")
        self.expected = artifact.identity("a" * 40, "1234", "2", self.sidecar)
        self.package = self.root / "package"
        self.output = self.root / "restored"

    def pack(self):
        artifact.pack(self.dist, self.package, self.expected)

    def rewrite_manifest(self, update):
        path = self.package / artifact.MANIFEST
        manifest = json.loads(path.read_text(encoding="utf-8"))
        update(manifest)
        path.write_text(json.dumps(manifest), encoding="utf-8")

    def assert_rejected_without_output(self, expected=None):
        with self.assertRaises(ValueError):
            artifact.restore(self.output, self.package, expected or self.expected)
        self.assertFalse(self.output.exists())

    def test_round_trip_preserves_exact_tree_including_hidden_assets(self):
        self.pack()
        artifact.restore(self.output, self.package, self.expected)
        def contents(root):
            return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        self.assertEqual(contents(self.dist), contents(self.output))

    def test_wrong_source_run_attempt_or_sidecar_is_rejected(self):
        self.pack()
        for key in self.expected:
            with self.subTest(key=key):
                self.assert_rejected_without_output({**self.expected, key: "different"})

    def test_sidecar_bytes_determine_identity(self):
        self.pack()
        self.sidecar.write_bytes(b"other-sidecar")
        changed = artifact.identity("a" * 40, "1234", "2", self.sidecar)
        self.assert_rejected_without_output(changed)

    def test_tampered_archive_and_file_hash_are_rejected(self):
        self.pack()
        archive = self.package / artifact.ARCHIVE
        original = archive.read_bytes()
        archive.write_bytes(original + b"tampered")
        self.assert_rejected_without_output()
        archive.write_bytes(original)
        self.rewrite_manifest(lambda m: m["files"]["assets/app.js"].update(sha256="0" * 64))
        self.assert_rejected_without_output()

    def test_missing_or_empty_required_file_is_rejected_at_pack(self):
        for name in artifact.REQUIRED:
            path = self.dist / name
            original = path.read_bytes()
            for content in (None, b""):
                with self.subTest(name=name, content=content):
                    if content is None:
                        path.unlink()
                    else:
                        path.write_bytes(content)
                    with self.assertRaises(ValueError):
                        self.pack()
                    self.assertFalse(self.package.exists())
            path.write_bytes(original)

    def test_missing_manifest_file_and_extra_archive_file_are_rejected(self):
        self.pack()
        manifest_path = self.package / artifact.MANIFEST
        original = manifest_path.read_bytes()
        self.rewrite_manifest(lambda m: m["files"].pop("splash.html"))
        self.assert_rejected_without_output()
        manifest_path.write_bytes(original)
        with zipfile.ZipFile(self.package / artifact.ARCHIVE, "a") as output:
            output.writestr("extra.js", "unrecorded")
        self.rewrite_manifest(lambda m: m.update(archive_sha256=artifact.digest(self.package / artifact.ARCHIVE)))
        self.assert_rejected_without_output()

    def test_archive_paths_and_symlinks_cannot_escape_destination(self):
        self.pack()
        manifest_path = self.package / artifact.MANIFEST
        original = manifest_path.read_bytes()
        for name, mode in (
            ("../escaped", 0), ("/absolute", 0), ("C:/escaped", 0), ("a\\escaped", 0),
            ("link", stat.S_IFLNK), ("CON.txt", 0), ("index.html.", 0), ("INDEX.HTML", 0),
            ("assets", 0), ("ASSETS", 0),
        ):
            with self.subTest(name=name):
                with zipfile.ZipFile(self.package / artifact.ARCHIVE, "w") as output:
                    for path in self.dist.rglob("*"):
                        if path.is_file():
                            output.write(path, path.relative_to(self.dist).as_posix())
                    item = zipfile.ZipInfo(name)
                    item.external_attr = mode << 16
                    output.writestr(item, b"escape")
                manifest_path.write_bytes(original)
                def update(m):
                    m["archive_sha256"] = artifact.digest(self.package / artifact.ARCHIVE)
                    m["files"][name] = {"bytes": 6, "sha256": hashlib.sha256(b"escape").hexdigest()}
                self.rewrite_manifest(update)
                self.assert_rejected_without_output()
                self.assertFalse((self.root / "escaped").exists())

    def test_stale_output_is_never_merged_or_removed(self):
        self.pack()
        self.output.mkdir()
        stale = self.output / "stale.js"
        stale.write_bytes(b"keep")
        with self.assertRaises(ValueError):
            artifact.restore(self.output, self.package, self.expected)
        self.assertEqual(stale.read_bytes(), b"keep")
        self.assertEqual(list(self.output.iterdir()), [stale])


if __name__ == "__main__":
    unittest.main()
