"""Exercise the command line contract with independent literal observations."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class Runner(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.fixtures = self.root / "fixtures"
        self.fixtures.mkdir()
        self.runner = self.root / "adapter-config.json"
        self.config = {
            "capabilities": {
                "target": "H8/38606F",
                "observations": ["er0"],
                "inputs": [],
                "conditions": {},
            },
            "report": {"fault": None, "completed": True, "er0": 1},
        }
        image = bytes(49152)
        eeprom = bytes([255]) * 65536
        (self.fixtures / "one.bin").write_bytes(image)
        (self.fixtures / "blank.bin").write_bytes(eeprom)
        self.corpus = {
            "target": "H8/38606F",
            "eeprom": {
                "file": "blank.bin",
                "sha256": hashlib.sha256(eeprom).hexdigest(),
            },
            "cases": [
                {
                    "name": "one",
                    "firmware": "one.bin",
                    "sha256": hashlib.sha256(image).hexdigest(),
                    "milliseconds": 8,
                    "input": None,
                    "input_sha256": None,
                    "conditions": {},
                    "expected": {"er0": 1},
                    "expectation": {
                        "kind": "software_reasoned",
                        "question": "Report the literal test value.",
                        "source": "Independent adapter fixture.",
                    },
                }
            ],
        }

    def run_suite(self, name="run", *options):
        self.runner.write_text(json.dumps(self.config))
        (self.fixtures / "manifest.json").write_text(json.dumps(self.corpus))
        out = self.root / name
        process = subprocess.run(
            [
                sys.executable,
                str(ROOT / "run.py"),
                "--fixtures",
                str(self.fixtures),
                "--out",
                str(out),
                "--adapter",
                str(ROOT / "tests/fake_adapter.py"),
                "--runner",
                str(self.runner),
                *options,
            ],
            capture_output=True,
            text=True,
        )
        report = (
            json.loads((out / "results.json").read_text())
            if (out / "results.json").exists()
            else None
        )
        return process, report, out

    def test_selection_listing_and_pass_artifact_policy(self):
        process, report, out = self.run_suite("listing", "--list", "--case", "on*")
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn("Independent adapter fixture.", process.stdout)
        self.assertFalse(out.exists())
        process, report, out = self.run_suite("unmatched", "--case", "missing")
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("no cases match", process.stderr)
        self.assertFalse(out.exists())
        process, report, out = self.run_suite("passed", "--case", "one")
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(report["counts"]["pass"], 1)
        self.assertFalse((out / "cases/one").exists())
        self.assertIn("sha256", report["source"]["adapter"])
        self.assertEqual(
            report["source"]["runner"]["sha256"],
            hashlib.sha256(self.runner.read_bytes()).hexdigest(),
        )
        process, report, out = self.run_suite("kept", "--keep-passed")
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertTrue((out / "cases/one/observations/observations.json").is_file())
        previous = (out / "results.json").read_bytes()
        process, _, _ = self.run_suite("kept")
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual((out / "results.json").read_bytes(), previous)

    def test_failure_keeps_observations_logs_and_exact_command(self):
        self.config["report"]["er0"] = 2
        process, report, out = self.run_suite()
        self.assertEqual(process.returncode, 1, process.stderr)
        result = report["results"][0]
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["failures"], ["er0: expected 1, got 2"])
        artifacts = Path(result["artifacts"])
        self.assertEqual(
            json.loads((artifacts / "observations/observations.json").read_text())[
                "er0"
            ],
            2,
        )
        self.assertIn("adapter stderr", (artifacts / "stderr.log").read_text())
        command = json.loads((artifacts / "command.json").read_text())
        self.assertEqual(command[command.index("--observe") + 1], "er0")

    def test_conditions_and_capabilities_determine_applicability_before_execution(self):
        case = self.corpus["cases"][0]
        case["conditions"] = {"supply_mv": 3000}
        self.config["capabilities"]["conditions"] = {"supply_mv": 2700}
        self.config["capabilities"]["observations"] = []
        timeline = b"0,digital,p31,1\n"
        (self.fixtures / "one.csv").write_bytes(timeline)
        case.update(input="one.csv", input_sha256=hashlib.sha256(timeline).hexdigest())
        process, report, out = self.run_suite()
        self.assertEqual(process.returncode, 2, process.stderr)
        self.assertEqual(report["counts"]["not_applicable"], 1)
        self.assertEqual(len(report["results"][0]["failures"]), 3)
        self.assertFalse((out / "cases").exists())

    def test_timeout_keeps_partial_logs_and_report(self):
        self.config["sleep"] = 5
        process, report, out = self.run_suite("timeout", "--timeout", "1")
        self.assertEqual(process.returncode, 1, process.stderr)
        self.assertEqual(report["counts"]["runner_error"], 1)
        self.assertIn("adapter stdout", (out / "cases/one/stdout.log").read_text())
        self.assertIn("adapter stderr", (out / "cases/one/stderr.log").read_text())

    def test_adapter_errors_are_distinct_from_hardware_mismatches(self):
        for name, report_value, returncode in [
            ("incomplete", {"fault": None, "completed": False}, 0),
            ("missing", {"fault": None, "completed": True}, 0),
            ("crash", None, 7),
        ]:
            with self.subTest(name=name):
                self.config.update(report=report_value, returncode=returncode)
                process, report, out = self.run_suite(name)
                self.assertEqual(process.returncode, 1, process.stderr)
                self.assertEqual(report["counts"]["runner_error"], 1)
                self.assertTrue((out / "cases/one/command.json").exists())

    def test_unresolved_expectations_are_not_reported_as_passes(self):
        self.corpus["cases"][0]["expectation"]["kind"] = "unresolved"
        self.corpus["cases"][0]["expected"] = {}
        process, report, out = self.run_suite()
        self.assertEqual(process.returncode, 2, process.stderr)
        self.assertEqual(report["counts"]["unknown"], 1)
        self.assertFalse((out / "cases").exists())
