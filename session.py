#!/usr/bin/env python3
"""Run supplied firmware sessions and check capture, replay and host-call boundaries."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import sys

import run as runner
from benchmark.process import parse_targets
from sessions.runner import SessionRunner, compare
from sessions.retail import verify

ROOT = Path(__file__).resolve().parent


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--target", nargs="+", action="append", metavar="NAME ADAPTER [EXECUTABLE]")
    p.add_argument("--firmware", type=Path)
    p.add_argument("--eeprom", type=Path)
    p.add_argument("--out", type=Path)
    p.add_argument("--scenarios", type=Path, default=ROOT / "sessions/retail/retail.json")
    p.add_argument("--case", action="append", default=[])
    p.add_argument("--quick", action="store_true")
    p.add_argument("--list", action="store_true")
    p.add_argument("--play", action="store_true")
    p.add_argument("--link", action="store_true")
    p.add_argument("--chunk-us", type=int)
    p.add_argument("--measure", action="store_true", help="measure end-to-end execution after verification")
    p.add_argument("--samples", type=int, default=3)
    p.add_argument("--timeout", type=float, default=900)
    args = p.parse_args()
    scenarios = json.loads(args.scenarios.read_text())["cases"]
    if set(args.case) - scenarios.keys():
        p.error("unknown session")
    selected = {name: case for name, case in scenarios.items()
                if (not args.quick or case["quick"]) and (not args.case or name in args.case)}
    if args.list:
        for name, case in selected.items():
            print(f"{name}: {case['milliseconds']} ms; {case['timeline'] or 'no external input'}")
        return
    if not args.target or not args.firmware or not args.eeprom or not args.out:
        p.error("--target, --firmware, --eeprom and --out are required")
    if args.samples < 2 or (args.chunk_us is not None and args.chunk_us < 1):
        p.error("samples must be at least two and chunk-us must be positive")
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    firmware, eeprom = args.firmware.resolve(), args.eeprom.resolve()
    inputs = {"firmware": runner.identity(firmware), "eeprom": runner.identity(eeprom),
              "scenarios": runner.identity(args.scenarios.resolve())}
    targets = parse_targets(args.target)
    report = {"suite": runner.checkout(ROOT), "inputs": inputs, "targets": {}, "failure": None}
    active = []
    baseline = {}
    try:
        for target in targets:
            directory = out / target.name
            directory.mkdir()
            session = SessionRunner(target, directory, args.timeout)
            active.append(session)
            entry = {"sources": session.sources, "sessions": [], "runs": session.records}
            report["targets"][target.name] = entry
            for name, case in selected.items():
                ms, checkpoint = case["milliseconds"], case.get("checkpoint_ms")
                timeline = args.scenarios.resolve().parent / case["timeline"] if case["timeline"] else None
                if timeline:
                    entry.setdefault("timelines", {})[name] = runner.identity(timeline)
                whole = session.execute(name, ms, firmware=firmware, eeprom=eeprom, inputs=timeline)
                errors = []
                if checkpoint:
                    prefix = session.execute(name + "-before", checkpoint, firmware=firmware,
                                             eeprom=eeprom, inputs=timeline)
                    resumed = session.execute(name + "-resumed", ms, inputs=timeline,
                                              restore=prefix.artifact("state"))
                    errors += compare(whole, resumed, prefix)
                if args.chunk_us:
                    chunked = session.execute(name + "-chunked", ms, firmware=firmware,
                                              eeprom=eeprom, inputs=timeline, chunk_us=args.chunk_us)
                    errors += compare(whole, chunked)
                if name in baseline:
                    errors += compare(baseline[name], whole)
                else:
                    baseline[name] = whole
                entry["sessions"].append({"name": name, "differences": errors})
                if errors:
                    raise ValueError(f"{target.name}/{name}: {errors}")
                print(f"PASS {target.name}/{name}", flush=True)
            if args.play:
                entry["sessions"].append(verify.play(session, firmware, eeprom))
                print(f"PASS {target.name}/play", flush=True)
            if args.link:
                entry["sessions"].append(verify.link(session, firmware, eeprom))
                print(f"PASS {target.name}/link", flush=True)
        # Alternate target order; trace/capture verification stays outside timing.
        if args.measure:
            for name, case in selected.items():
                timeline = args.scenarios.resolve().parent / case["timeline"] if case["timeline"] else None
                samples = {s.target.name: [] for s in active}
                for repeat in range(args.samples):
                    for s in active[::1 if repeat % 2 == 0 else -1]:
                        measured = s.execute(f"{name}-sample-{repeat}", case["milliseconds"],
                                             firmware=firmware, eeprom=eeprom, inputs=timeline,
                                             history=False, chunk_us=args.chunk_us)
                        errors = compare(baseline[name], measured, history=False)
                        if errors:
                            raise ValueError(f"timed session differs: {errors}")
                        samples[s.target.name].append(s.records[-1])
                for s in active:
                    values = samples[s.target.name]
                    summary = {key: {"median": statistics.median(v[key] for v in values),
                                     "min": min(v[key] for v in values), "max": max(v[key] for v in values)}
                               for key in ("process_wall_seconds", "process_cpu_seconds", "run_seconds")}
                    report["targets"][s.target.name].setdefault("timing", {})[name] = summary
                    print(f"{name} {s.target.name}: {summary['process_wall_seconds']['median']:.6f} s end-to-end", flush=True)
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        report["failure"] = str(error)
    finally:
        for s in active:
            entry = report["targets"][s.target.name]
            entry["sources_unchanged"] = s.unchanged()
            if not entry["sources_unchanged"]:
                report["failure"] = "sources or executable changed during execution"
        if inputs != {"firmware": runner.identity(firmware), "eeprom": runner.identity(eeprom),
                      "scenarios": runner.identity(args.scenarios.resolve())}:
            report["failure"] = "input images or scenarios changed during execution"
        runner.write_json(out / "results.json", report)
    if report["failure"]:
        raise RuntimeError(report["failure"])
    print(f"Firmware sessions passed. Results: {out}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        sys.exit(str(error))
