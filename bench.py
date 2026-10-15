#!/usr/bin/env python3
"""Compare Pokéwalker hardware conformance and per-workload speed."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import sys
from fnmatch import fnmatchcase

import run as runner
from benchmark import coverage, workloads
from benchmark.conformance import audit_cases, audit_workloads, build_fixtures, conformance
from benchmark.process import parse_targets
from benchmark.report import report
from benchmark.score import score
from benchmark.speed import measure, write_fixture

ROOT = Path(__file__).resolve().parent


def select_workloads(seed: int, patterns: list[str]):
    chosen = [w for w in workloads(seed)
              if not patterns or any(fnmatchcase(w.name, p) for p in patterns)]
    if patterns and not chosen:
        raise ValueError("no workloads match")
    return chosen


def describe_targets(targets, out: Path, timeout: float) -> dict:
    described = {}
    (out / "describe").mkdir()
    for target in targets:
        target.capabilities = runner.describe(target.command, out / "describe" / target.name,
                                              timeout)
        described[target.name] = {"command": target.command, "sources": target.sources(),
                                  "capabilities": target.capabilities}
    return described


def common(parser):
    parser.add_argument("--target", nargs="+", action="append", required=True,
                        metavar=("NAME", "ADAPTER"), help="NAME ADAPTER [EMULATOR]; repeat")
    parser.add_argument("--out", type=Path, required=True, help="new result directory")
    parser.add_argument("--seed", type=int, help="workload seed (default: random)")
    parser.add_argument("--workload", action="append", default=[], metavar="PATTERN")
    parser.add_argument("--case", action="append", default=[], metavar="PATTERN")
    parser.add_argument("--timeout", type=float, default=120,
                        help="seconds per adapter run before calibration (default 120)")
    parser.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) // 2),
                        help="parallel conformance runs (workload timing is serial)")
    parser.add_argument("--cpu", type=int, help="pin timed adapter processes to this CPU")


def audit(targets, chosen, seed, out: Path, args) -> dict:
    findings = {}
    fixtures = out / "audit-case-fixtures"
    if not args.skip_conformance:
        build_fixtures(fixtures, args.case)
    other = select_workloads(seed + 1, args.workload) if not args.skip_workloads else []
    for target in targets:
        found = []
        if not args.skip_conformance:
            found += audit_cases(target, fixtures, out / "audit" / target.name / "cases", args)
        if not args.skip_workloads:
            found += audit_workloads(target, chosen, other, out / "audit-workload-fixtures",
                                     out / "audit" / target.name / "workloads", args)
        findings[target.name] = found
        print(f"audit {target.name}: {len(found)} findings", flush=True)
    return findings


def save_results(results: dict, targets, out: Path) -> None:
    """Keep invalid runs reviewable without assigning them benchmark scores."""
    results["host"]["loadavg_end"] = os.getloadavg()
    changed = []
    for target in targets:
        try:
            after = target.sources()
        except OSError as error:
            after = {"error": str(error)}
        entry = results["targets"][target.name]
        entry["sources_after"] = after
        entry["sources_changed"] = after != entry["sources"]
        if entry["sources_changed"]:
            changed.append(target.name)
    if changed:
        results["runner_error"] = f"sources or executables changed during run: {', '.join(changed)}"
    audit_failed = any(results.get("audit", {}).values())
    results["scores"] = {} if changed or audit_failed else score(results)
    (out / "results.json").write_text(json.dumps(results, indent=2, default=str) + "\n")
    report(results)
    print(f"\nResults: {out / 'results.json'}")
    if changed or audit_failed:
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    go = sub.add_parser("run", help="run conformance cases and timed workloads")
    common(go)
    go.add_argument("--skip-conformance", action="store_true")
    go.add_argument("--skip-workloads", action="store_true")
    go.add_argument("--audit", action="store_true", help="also run the discrimination audit")
    go.add_argument("--samples", type=int, default=5)
    go.add_argument("--min-seconds", type=float, default=2.0,
                    help="emulation wall time beyond the base run per sample (default 2)")
    check = sub.add_parser("audit", help="run every case and workload against failing controls")
    common(check)
    check.add_argument("--skip-conformance", action="store_true")
    check.add_argument("--skip-workloads", action="store_true")
    show = sub.add_parser("report", help="print a results.json")
    show.add_argument("results", type=Path)
    listing = sub.add_parser("list", help="list workloads and the coverage map")
    listing.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    if args.command == "report":
        report(json.loads(args.results.read_text()))
        return
    if args.command == "list":
        chosen = list(workloads(args.seed))
        for w in chosen:
            print(f"{w.name} [{w.tier}, {w.evidence['kind']}, horizons "
                  f"{w.horizons[0]}..{w.horizons[-1]} ms]")
            print(f"  {w.summary}")
            print(f"  Blocks: {', '.join(w.blocks)}")
            print(f"  Source: {w.evidence['source']}")
        coverage.print_map([w.name for w in chosen])
        return

    seed = args.seed if args.seed is not None else random.SystemRandom().randrange(1 << 31)
    targets = parse_targets(args.target)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    chosen = select_workloads(seed, args.workload) if not args.skip_workloads else []
    results = {
        "seed": seed,
        "suite": runner.checkout(ROOT),
        "host": {"platform": platform.platform(), "processor": platform.processor(),
                 "cpus": os.cpu_count(), "python": sys.version,
                 "loadavg_start": os.getloadavg()},
        "settings": {k: v for k, v in vars(args).items()
                     if k not in ("target", "out", "command")},
        "targets": describe_targets(targets, out, args.timeout),
    }
    if args.command == "audit":
        results["audit"] = audit(targets, chosen, seed, out, args)
        save_results(results, targets, out)
        return

    if args.samples < 3:
        parser.error("--samples must be at least 3")
    if not args.skip_conformance:
        fixtures = out / "case-fixtures"
        manifest = build_fixtures(fixtures, args.case)
        results["cases"] = manifest["cases"]
        results["fixture_manifest_sha256"] = hashlib.sha256(
            (fixtures / "manifest.json").read_bytes()).hexdigest()
        results["conformance"] = conformance(targets, fixtures, out / "cases", args)
    if chosen:
        fixtures = out / "workload-fixtures"
        results["fixtures"] = {w.name: write_fixture(w, fixtures / w.name) for w in chosen}
        results["workloads"] = measure(chosen, targets, fixtures, out / "runs", args)
    if args.audit:
        results["audit"] = audit(targets, chosen, seed, out, args)
    save_results(results, targets, out)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError) as error:
        raise SystemExit(str(error))
