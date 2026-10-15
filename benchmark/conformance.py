"""Conformance runs and the discrimination audit.

Every conformance case runs on every target. The audit runs the same cases and
workloads with the guest replaced by a program that does nothing, and with a
workload's image, EEPROM and inputs taken from a different seed. A case or
workload that still passes cannot tell a working emulator from one that runs
nothing, or does not depend on its seeded data; such a check gives credit
without evidence and must be fixed.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import run as runner
from diagnostic import select

ROOT = Path(__file__).resolve().parents[1]
# Every vector reaches the idle loop, so external NMI/reset inputs cannot turn
# an otherwise valid control into a decode fault.
NULL_IMAGE = bytes.fromhex("0100") * 64 + bytes(0x80) + bytes.fromhex("40fe") + bytes(49152 - 0x102)


def build_fixtures(directory: Path, patterns: list[str]) -> dict:
    command = [sys.executable, str(ROOT / "build.py"), str(directory)]
    for pattern in patterns:
        command += ["--case", pattern]
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
    return runner.load_manifest(directory)


def run_cases(target, cases: list[dict], fixtures: Path, eeprom: str, work: Path,
              jobs: int, timeout: float, target_id: str) -> dict:
    def one(case):
        if case["expectation"]["kind"] == "unresolved":
            return {"status": "unknown", "failures": ["expectation is unresolved"]}
        reasons = runner.applicability(case, target.capabilities, target_id, fixtures)
        if reasons:
            return {"status": "not_applicable", "failures": reasons}
        result = runner.run_case(case, target.command, fixtures, eeprom,
                                 work / case["name"], timeout, False)
        result.pop("wall_seconds", None)
        return result

    with ThreadPoolExecutor(jobs) as pool:
        results = list(pool.map(one, cases))
    return {case["name"]: result for case, result in zip(cases, results)}


def conformance(targets, fixtures: Path, work: Path, args) -> dict:
    manifest = runner.load_manifest(fixtures)
    cases = select(manifest["cases"], args.case)
    out = {}
    for target in targets:
        out[target.name] = run_cases(target, cases, fixtures, manifest["eeprom"]["file"],
                                     work / target.name, args.jobs, args.timeout,
                                     manifest["target"])
        counts = {}
        for result in out[target.name].values():
            counts[result["status"]] = counts.get(result["status"], 0) + 1
        print(f"conformance {target.name}: {counts}", flush=True)
    return out


def audit_cases(target, fixtures: Path, work: Path, args) -> list[dict]:
    """Cases that pass with the null program on this target."""
    null = work / "null-fixtures"
    shutil.copytree(fixtures, null)
    manifest = json.loads((null / "manifest.json").read_text())
    digest = hashlib.sha256(NULL_IMAGE).hexdigest()
    for case in manifest["cases"]:
        (null / case["firmware"]).write_bytes(NULL_IMAGE)
        case["sha256"] = digest
    (null / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    cases = select(manifest["cases"], args.case)
    results = run_cases(target, cases, null, manifest["eeprom"]["file"], work / "null-runs",
                        args.jobs, args.timeout, manifest["target"])
    findings = []
    for name, result in results.items():
        if result["status"] == "pass":
            findings.append({"case": name, "control": "null program", "reason": "check passed"})
        elif not result.get("execution_completed"):
            findings.append({"case": name, "control": "null program",
                             "reason": "control did not complete", "result": result})
    return findings


def audit_workloads(target, workloads, other, fixtures: Path, work: Path, args) -> list[dict]:
    """Workloads whose first horizon passes a null program or another seed's data."""
    from .speed import execute, input_file, verify, write_fixture

    findings = []
    foreign = {w.name: w for w in other}
    for workload in workloads:
        h = workload.horizons[1]
        fixture = fixtures / workload.name
        if not fixture.exists():
            write_fixture(workload, fixture)
        null = fixture / "null.bin"
        null.write_bytes(NULL_IMAGE)
        swap = foreign[workload.name]
        swapped = work / workload.name / "foreign-fixture"
        write_fixture(swap, swapped)
        controls = (
            ("null", "null program", fixture, workload, null),
            ("foreign", f"seed {swap.seed} data", swapped, swap, None),
        )
        for directory, label, image, inputs, firmware in controls:
            record = execute(target, workload, work / workload.name / directory, image, h,
                             input_file(inputs, image, h), args.timeout, args.cpu, firmware)
            failures = verify(workload, h, record)
            finding = {"workload": workload.name, "control": label}
            if record.get("error") or record["status"]:
                findings.append(finding | {
                    "reason": "control did not complete",
                    "error": record.get("error") or f"exit status {record['status']}",
                })
            elif not failures:
                findings.append(finding | {"reason": "check passed"})
    return findings
