"""Workload timing: every run is timed and checked, and the two are kept apart.

Every run that completes is timed and checked. Speed and correctness are
recorded separately: a run that fails its checks still yields a duration, and
the check result decides only whether that duration enters the verified
figures.

For each workload and target the base run is the workload's first horizon H0.
Calibration runs successively longer horizons until a run takes long enough to
estimate the emulation rate, then picks the shortest horizon H expected to
spend at least ``--min-seconds`` beyond H0. Each sample runs H0 and H with the
same input file and observations and records ``T(H) - T(H0)``, which removes
process start-up, image loading, input parsing and result export, and also the
guest's set-up phase. Speed is ``(H - H0) / median(T(H) - T(H0))`` in emulated
seconds per host second. Samples alternate target order and run order.

A target whose adapter declares that it converts one of a workload's inputs in
place of the core (``assists`` in its description) runs the workload as usual;
the result is marked assisted and is never verified, because the timed work is
not the same as a core doing that conversion itself.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import statistics
import subprocess
from pathlib import Path

from diagnostic import STORAGE, TARGET
from .process import timed_invoke

CALIBRATION_SECONDS = 0.25
# A timed process tree busy for less of the wall time than this was waiting
# (pacing, I/O or another process), so wall time does not measure emulation.
WAITING_SHARE = 0.9
# Samples spreading more than this around their median are reported as noisy.
NOISY_SPREAD = 0.25


def write_fixture(workload, directory: Path) -> dict:
    directory.mkdir(parents=True)
    (directory / "firmware.bin").write_bytes(workload.image)
    eeprom = workload.eeprom or bytes([255]) * 65536
    (directory / "eeprom.bin").write_bytes(eeprom)
    return {"seed": workload.seed,
            "firmware_sha256": hashlib.sha256(workload.image).hexdigest(),
            "eeprom_sha256": hashlib.sha256(eeprom).hexdigest()}


def input_file(workload, directory: Path, horizon: int) -> Path | None:
    if workload.timeline is None:
        return None
    path = directory / f"input-{horizon}.csv"
    if not path.exists():
        path.write_text(workload.timeline(horizon))
    return path


def applicability(workload, capabilities: dict) -> list[str]:
    reasons = []
    if capabilities["target"] != TARGET:
        reasons.append(f"target requires {TARGET}; adapter provides {capabilities['target']}")
    for field in sorted(set(workload.observe) - set(capabilities["observations"])):
        reasons.append(f"observation unavailable: {field}")
    for kind in sorted(set(workload.inputs) - set(capabilities["inputs"])):
        reasons.append(f"input unavailable: {kind}")
    return reasons


def assistance(workload, capabilities: dict) -> dict:
    """Inputs of the workload whose conversion the adapter does in place of the core."""
    assists = capabilities.get("assists", {})
    return {kind: assists[kind] for kind in workload.inputs if kind in assists}


def execute(target, workload, directory: Path, fixture: Path, horizon: int,
            input_path: Path | None, timeout: float, cpu: int | None,
            firmware: Path | None = None) -> dict:
    output = directory / "observations"
    command = [*target.command, "--firmware", str(firmware or fixture / "firmware.bin"),
               "--eeprom", str(fixture / "eeprom.bin"),
               "--milliseconds", str(horizon), "--out", str(output)]
    for field in workload.observe:
        command += ["--observe", field]
    if input_path:
        command += ["--input", str(input_path)]
    try:
        status, wall, cpu_seconds = timed_invoke(command, directory, timeout, cpu)
    except subprocess.TimeoutExpired:
        return {"status": None, "wall": None, "cpu": None, "observed": None,
                "error": f"timed out after {timeout:.0f} s"}
    record = {"status": status, "wall": wall, "cpu": cpu_seconds, "observed": None}
    try:
        report = json.loads((output / "observations.json").read_text())
    except (OSError, ValueError) as error:
        record["error"] = f"adapter exited with status {status} without observations ({error})"
        return record
    if report.get("fault") is not None:
        record["error"] = f"guest execution stopped: {report['fault']}"
        return record
    if report.get("completed") is not True:
        record["error"] = "adapter did not complete the observation period"
        return record
    observed = {}
    for field in workload.observe:
        if field in STORAGE:
            path = output / f"{field}.bin"
            if path.exists():
                observed[field] = path.read_bytes()
        elif field in report:
            observed[field] = report[field]
    record["observed"] = observed
    for field in workload.observe:
        if field not in observed:
            record["error"] = f"{field} not exported"
            break
        if field in STORAGE and len(observed[field]) != STORAGE[field][1]:
            record["error"] = f"adapter exported wrong {field} size"
            break
    return record


def verify(workload, horizon: int, record: dict) -> list[str]:
    if record.get("error"):
        return [record["error"]]
    for field in workload.observe:
        if field not in record["observed"]:
            return [f"{field} not exported"]
    try:
        failures = workload.check(horizon, record["observed"])
    except (ValueError, KeyError, IndexError) as error:
        record["error"] = f"observations could not be checked: {error}"
        failures = [record["error"]]
    if record["status"] and not failures:
        failures.append(f"adapter exited with status {record['status']}")
    return failures


def run_verified(target, workload, directory, fixture, horizon, input_path, timeout,
                 cpu) -> tuple[dict, list[str]]:
    record = execute(target, workload, directory, fixture, horizon, input_path, timeout, cpu)
    failures = verify(workload, horizon, record)
    if not failures:
        shutil.rmtree(directory, ignore_errors=True)
    return record, failures


def note(result: dict, place: Path, horizon: int, failures: list[str], label: str):
    """Record a check failure; the first one is kept with its artifacts."""
    result.setdefault("failed_runs", 0)
    result["failed_runs"] += 1
    if result["status"] == "accurate":
        result.update(status="inaccurate", artifacts=str(place),
                      failures=[f"{label} at {horizon} ms: {f}" for f in failures])
    else:
        shutil.rmtree(place, ignore_errors=True)


def timed_run(target, workload, place, fixture, horizon, input_path, timeout, cpu,
              result, label):
    """One timed run, checked. Returns its record, or None if it could not be timed."""
    record, failures = run_verified(target, workload, place, fixture, horizon, input_path,
                                    timeout, cpu)
    result["runs"] = result.get("runs", 0) + 1
    if record.get("error") or record["wall"] is None:
        # A run that faults, times out or does not complete has no meaningful duration.
        result.update(status="error", artifacts=str(place),
                      failures=[f"{label} at {horizon} ms: {f}" for f in failures])
        return None
    if failures:
        note(result, place, horizon, failures, label)
    return record


def calibrate(workload, target, fixture: Path, directory: Path, result: dict, args):
    """Run and check the first horizons and choose the timed horizon.

    Runs are timed whether or not they pass their checks; check results are
    kept beside the timing and decide only the verified figures.
    """
    h0 = workload.horizons[0]
    result.update(status="accurate", failures=[])
    timings = {}
    index = 1
    while True:
        horizon = workload.horizons[index]
        path = input_file(workload, fixture, horizon)
        for h in (h0, horizon):
            record = timed_run(target, workload, directory / f"calibrate-{h}", fixture, h,
                               path, args.timeout, args.cpu, result, "calibration")
            if record is None:
                return None
            timings[h] = record["wall"]
        span = timings[horizon] - timings[h0]
        rate = max(span, 1e-4) / (horizon - h0)
        if span >= CALIBRATION_SECONDS or index == len(workload.horizons) - 1:
            break
        # Jump to the first horizon expected to reach the calibration span.
        index = next((i for i in range(index + 1, len(workload.horizons))
                      if rate * (workload.horizons[i] - h0) >= CALIBRATION_SECONDS),
                     len(workload.horizons) - 1)
    chosen = next((h for h in workload.horizons[1:] if rate * (h - h0) >= args.min_seconds),
                  workload.horizons[-1])
    predicted = rate * chosen + timings[h0]
    result.update(horizon_ms=chosen, base_ms=h0)
    return {"horizon": chosen, "timeout": max(args.timeout, 20 * predicted + 10),
            "samples": []}


def sample(workload, target, fixture, directory, plan, result, index, args, input_path):
    if result["status"] == "error":
        return
    runs = {}
    order = ("base", "horizon") if index % 2 == 0 else ("horizon", "base")
    for kind in order:
        horizon = workload.horizons[0] if kind == "base" else plan["horizon"]
        record = timed_run(target, workload, directory / f"sample-{index}-{kind}", fixture,
                           horizon, input_path, plan["timeout"], args.cpu, result,
                           f"sample {index}")
        if record is None:
            return
        runs[kind] = {"wall": record["wall"], "cpu": record["cpu"]}
    plan["samples"].append(runs)


def summarize(workload, plan, result, min_seconds):
    if result["status"] == "error":
        return
    samples = plan["samples"]
    h0, h = workload.horizons[0], plan["horizon"]
    record = {"horizon_ms": h, "base_ms": h0, "samples": len(samples), "timing": {}}
    for clock in ("wall", "cpu"):
        spans = [s["horizon"][clock] - s["base"][clock] for s in samples]
        if spans:
            record["timing"][clock] = {
                "spans": spans, "median": statistics.median(spans),
                "min": min(spans), "max": max(spans),
                "base_median": statistics.median(s["base"][clock] for s in samples),
            }
    wall = record["timing"].get("wall")
    if wall and wall["median"] > 0:
        emulated = (h - h0) / 1000
        record["x_realtime"] = {clock: emulated / t["median"]
                                for clock, t in record["timing"].items() if t["median"] > 0}
        record["spread"] = (wall["max"] - wall["min"]) / wall["median"]
        if wall["median"] < min_seconds / 2:
            record["short_horizon"] = True
        cpu = record["timing"].get("cpu")
        if cpu and cpu["median"] > 0:
            record["cpu_share"] = cpu["median"] / wall["median"]
            if record["cpu_share"] < WAITING_SHARE:
                record["waiting"] = True
        if record["spread"] > NOISY_SPREAD:
            record["noisy"] = True
        base_units, units = workload.units(h0), workload.units(h)
        record["ns_per_unit"] = {
            unit: wall["median"] * 1e9 / (count - base_units.get(unit, 0))
            for unit, count in units.items() if count > base_units.get(unit, 0)}
    result.update(record)
    result["verified"] = result["status"] == "accurate" and not result.get("assisted")


def measure(workloads, targets, fixtures: Path, work: Path, args) -> list[dict]:
    rows = []
    for workload in workloads:
        fixture = fixtures / workload.name
        row = {"workload": workload.name, "tier": workload.tier, "blocks": workload.blocks,
               "summary": workload.summary, "evidence": workload.evidence,
               "seed": workload.seed, "targets": {}}
        plans = {}
        for target in targets:
            result = {"status": None, "failures": []}
            row["targets"][target.name] = result
            reasons = applicability(workload, target.capabilities)
            if reasons:
                result.update(status="not_applicable", failures=reasons)
                continue
            assists = assistance(workload, target.capabilities)
            if assists:
                result["assisted"] = assists
            plan = calibrate(workload, target, fixture, work / workload.name / target.name,
                             result, args)
            if plan is not None:
                plans[target.name] = plan
        timed = [t for t in targets if t.name in plans]
        # One input file serves every timed run of this workload.
        longest = max((p["horizon"] for p in plans.values()), default=None)
        input_path = input_file(workload, fixture, longest) if longest else None
        for index in range(args.samples):
            order = timed if index % 2 == 0 else list(reversed(timed))
            for target in order:
                sample(workload, target, fixture, work / workload.name / target.name,
                       plans[target.name], row["targets"][target.name], index, args,
                       input_path)
        for target in timed:
            summarize(workload, plans[target.name], row["targets"][target.name],
                      args.min_seconds)
        rows.append(row)
        cells = "  ".join(f"{name}: {describe(r)}" for name, r in row["targets"].items())
        print(f"{workload.name:<16} {cells}", flush=True)
    return rows


def describe(result: dict) -> str:
    if "x_realtime" in result:
        verdict = ("verified" if result["verified"]
                   else "FAILED CHECKS" if result["status"] != "accurate" else "assisted")
        return f"{result['x_realtime']['wall']:.1f}x ({verdict})"
    return result["status"]
