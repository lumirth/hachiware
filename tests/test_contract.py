from __future__ import annotations
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import manifest
import run as suite


class Conformance(unittest.TestCase):
    def test_checkout_fingerprints_dirty_contents_and_ignores_run_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def git(*args):
                subprocess.run(
                    ["git", "-C", str(root), *args], check=True, capture_output=True
                )

            git("init", "-q")
            (root / ".gitignore").write_text("out/\n")
            (root / "source").write_text("original")
            git("add", ".")
            git(
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.invalid",
                "-c",
                "commit.gpgsign=false",
                "-c",
                "core.hooksPath=/dev/null",
                "commit",
                "-qm",
                "fixture",
            )
            (root / "source").write_text("first")
            before = suite.checkout(root)
            (root / "source").write_text("other")
            after = suite.checkout(root)
            self.assertEqual(before["commit"], after["commit"])
            self.assertEqual(before["changes"], after["changes"])
            self.assertNotEqual(before["tree_sha256"], after["tree_sha256"])
            (root / "new\nfile").write_bytes(b"\x00\xff")
            untracked = suite.checkout(root)
            self.assertNotEqual(after["tree_sha256"], untracked["tree_sha256"])
            (root / "out").mkdir()
            (root / "out/result").write_text("ignored")
            self.assertEqual(
                untracked["tree_sha256"], suite.checkout(root / "out")["tree_sha256"]
            )

    def test_rejects_misspelled_and_out_of_range_expectations(self):
        for expected in [
            {"interrupt_entry": 1},
            {"ram": {"0000": "01"}},
            {"ram": {"ff7f": "abcd"}},
            {"eeprom": {"ffff": "0102"}},
            {"ram": {"f800": ""}},
            {"er0": 1 << 32},
            {"display_on": 1},
            {"ir_events": True},
            {"pixels": {"1800": "01"}},
            {"pixels": {"0000": "04"}},
            {"icons": {"0100": "00"}},
        ]:
            with self.subTest(expected=expected), self.assertRaises(ValueError):
                manifest.validate_expected(expected)
        manifest.validate_expected(
            {"ram": {"f780": "00", "ff7f": "ab"}, "interrupt_entries": 1}
        )

    def test_all_firmware_timeline_and_eeprom_inputs_are_hashed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "fixtures"
            subprocess.run(
                [sys.executable, str(ROOT / "build.py"), str(root)],
                check=True,
                capture_output=True,
            )
            corpus = manifest.load_manifest(root)
            self.assertTrue(corpus["cases"])
            for name in [
                "blank-eeprom.bin",
                "register-aliases.bin",
                "nmi-masked-sleep.csv",
            ]:
                path = root / name
                data = path.read_bytes()
                path.write_bytes(bytes([data[0] ^ 1]) + data[1:])
                with self.subTest(name=name), self.assertRaises(ValueError):
                    manifest.load_manifest(root)
                path.write_bytes(data)
            self.assertEqual(manifest.load_manifest(root), corpus)

    def test_fixture_paths_cannot_escape_the_selected_corpus(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ["../other.bin", "/tmp/file", ".", "", "a/b"]:
                with self.subTest(name=name), self.assertRaises(ValueError):
                    manifest.checked_file(Path(d), name, "0" * 64)

    def test_compares_requested_observations_without_clock_or_memory_exports(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            report = {"fault": None, "completed": True, "interrupt_entries": 0}
            self.assertEqual(
                suite.compare({"interrupt_entries": 1}, report, root),
                ["interrupt_entries: expected 1, got 0"],
            )
            report["interrupt_entries"] = 1
            self.assertEqual(suite.compare({"interrupt_entries": 1}, report, root), [])
            report["completed"] = False
            with self.assertRaisesRegex(ValueError, "observation period"):
                suite.compare({"interrupt_entries": 1}, report, root)
            report["completed"] = True
            report["interrupt_entries"] = True
            with self.assertRaisesRegex(ValueError, "type"):
                suite.compare({"interrupt_entries": 1}, report, root)

    def test_unknown_or_unmeasured_expectations_cannot_be_labeled_hardware(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "fixtures"
            subprocess.run(
                [sys.executable, str(ROOT / "build.py"), str(root)],
                check=True,
                capture_output=True,
            )
            path = root / "manifest.json"
            data = json.loads(path.read_text())
            data["cases"][0]["expectation"]["kind"] = "hardware_measured"
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "captured observation"):
                manifest.load_manifest(root)
