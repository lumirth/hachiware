#!/usr/bin/env python3
"""Run selected diagnostics and retain observations from failures."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

from diagnostic import SCALARS, STORAGE, listing, select
from manifest import load_manifest, required_inputs

ROOT = Path(__file__).resolve().parent


def compare(expected: dict, report: dict, output: Path) -> list[str]:
    if report["fault"] is not None:
        if not isinstance(report["fault"], str):
            raise ValueError("fault must be a description or null")
        return [f"guest execution stopped: {report['fault']}"]
    if report["completed"] is not True:
        raise ValueError("adapter did not complete the observation period")
    failures = []
    for domain, (start, size) in STORAGE.items():
        if domain not in expected:
            continue
        data = (output / f"{domain}.bin").read_bytes()
        if len(data) != size:
            raise ValueError(f"adapter exported wrong {domain} size")
        for address, text in expected[domain].items():
            offset = int(address, 16) - start
            wanted = bytes.fromhex(text)
            actual = data[offset : offset + len(wanted)]
            if actual != wanted:
                failures.append(
                    f"{domain}[{address}]: expected {wanted.hex()}, got {actual.hex()}"
                )
    for key in expected.keys() & SCALARS:
        actual = report[key]
        if type(actual) is not type(expected[key]):
            raise ValueError(f"adapter exported wrong {key} type")
        if actual != expected[key]:
            failures.append(f"{key}: expected {expected[key]}, got {actual}")
    return failures


def applicability(
    case: dict, capabilities: dict, target: str, fixtures: Path
) -> list[str]:
    reasons = []
    if capabilities["target"] != target:
        reasons.append(
            f"target requires {target}; adapter provides {capabilities['target']}"
        )
    for field in sorted(case["expected"].keys() - set(capabilities["observations"])):
        reasons.append(f"observation unavailable: {field}")
    inputs = required_inputs(fixtures / case["input"] if case["input"] else None)
    for kind in sorted(inputs - set(capabilities["inputs"])):
        reasons.append(f"input unavailable: {kind}")
    for name, wanted in case["conditions"].items():
        actual = capabilities["conditions"].get(name)
        if actual != wanted or isinstance(actual, bool) != isinstance(wanted, bool):
            reasons.append(
                f"condition {name}: requires {wanted!r}, adapter provides {actual!r}"
            )
    return reasons


def checkout(directory: Path) -> dict:
    try:
        command = ["git", "--no-optional-locks", "-C", str(directory)]

        def git(*args: str) -> bytes:
            return subprocess.check_output([*command, *args], stderr=subprocess.DEVNULL)

        root = Path(os.fsdecode(git("rev-parse", "--show-toplevel")).strip())
        command = ["git", "--no-optional-locks", "-C", str(root)]
        commit = git("rev-parse", "HEAD").decode().strip()
        changes = (
            git("status", "--porcelain", "--untracked-files=all").decode().splitlines()
        )
        names = git("ls-files", "--cached", "--others", "--exclude-standard", "-z")
        tree = hashlib.sha256()
        for name in sorted(set(names.split(b"\0")) - {b""}):
            path = root / os.fsdecode(name)
            if path.is_symlink():
                kind, value = (
                    "symlink",
                    hashlib.sha256(os.fsencode(os.readlink(path))).hexdigest(),
                )
            elif path.is_file():
                kind, value = (
                    "executable" if path.stat().st_mode & 0o111 else "file",
                    identity(path)["sha256"],
                )
            elif not path.exists():
                kind, value = "missing", ""
            else:
                raise OSError(f"cannot fingerprint {path}")
            tree.update(json.dumps([os.fsdecode(name), kind, value]).encode() + b"\n")
        return {
            "commit": commit,
            "dirty": bool(changes),
            "changes": changes,
            "tree_sha256": tree.hexdigest(),
        }
    except (OSError, subprocess.CalledProcessError) as error:
        return {"commit": None, "dirty": None, "tree_sha256": None, "error": str(error)}


def identity(path: Path) -> dict:
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def sources(adapter: Path, runner: Path | None) -> dict:
    return {
        "suite": checkout(ROOT),
        "suite_runner": identity(Path(__file__).resolve()),
        "adapter": {**identity(adapter), "checkout": checkout(adapter.parent)},
        "runner": identity(runner.resolve()) if runner else None,
        "python": sys.version,
    }


def write_json(path: Path, value) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")


def invoke(command: list[str], directory: Path, timeout: float) -> int:
    """Keep the command and both output streams even after a timeout."""
    write_json(directory / "command.json", command)
    with (
        (directory / "stdout.log").open("xb") as stdout,
        (directory / "stderr.log").open("xb") as stderr,
    ):
        with subprocess.Popen(
            command, stdout=stdout, stderr=stderr, start_new_session=os.name == "posix"
        ) as process:
            try:
                return process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                # The adapter may have started an emulator process of its own.
                if os.name == "posix":
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                else:
                    try:
                        subprocess.run(
                            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            check=False,
                            timeout=5,
                        )
                    except (OSError, subprocess.TimeoutExpired):
                        pass
                    finally:
                        if process.poll() is None:
                            process.kill()
                process.wait()
                raise


def describe(command: list[str], directory: Path, timeout: float) -> dict:
    directory.mkdir()
    if invoke([*command, "--describe"], directory, timeout):
        raise ValueError(f"adapter description failed; see {directory}")
    caps = json.loads((directory / "stdout.log").read_text())
    if not isinstance(caps, dict):
        raise ValueError("adapter description must be an object")
    if not isinstance(caps.get("target"), str) or not caps["target"]:
        raise ValueError("adapter must identify its target")
    for key in ("observations", "inputs"):
        if not isinstance(caps.get(key), list) or any(
            not isinstance(v, str) for v in caps[key]
        ):
            raise ValueError(f"adapter must list available {key}")
    if not isinstance(caps.get("conditions"), dict):
        raise ValueError("adapter must describe its configured conditions")
    return caps


def run_case(
    case: dict,
    command: list[str],
    fixtures: Path,
    eeprom: str,
    directory: Path,
    timeout: float,
    keep_passed: bool,
) -> dict:
    directory.mkdir(parents=True)
    output = directory / "observations"
    command = [
        *command,
        "--firmware",
        str(fixtures / case["firmware"]),
        "--eeprom",
        str(fixtures / eeprom),
        "--milliseconds",
        str(case["milliseconds"]),
        "--out",
        str(output),
    ]
    for observation in sorted(case["expected"]):
        command += ["--observe", observation]
    if case["input"]:
        command += ["--input", str(fixtures / case["input"])]
    started = time.monotonic()
    try:
        returncode = invoke(command, directory, timeout)
        if returncode and not (output / "observations.json").is_file():
            status, failures = (
                "runner_error",
                [f"adapter exited with status {returncode}"],
            )
        else:
            report = json.loads((output / "observations.json").read_text())
            failures = compare(case["expected"], report, output)
            if returncode and not failures:
                raise ValueError(
                    f"adapter exited with status {returncode} after reporting completion"
                )
            status = "fail" if failures else "pass"
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.TimeoutExpired,
    ) as error:
        status, failures = "runner_error", [str(error)]
    result = {
        "status": status,
        "failures": failures,
        "wall_seconds": time.monotonic() - started,
    }
    if status == "pass" and not keep_passed:
        shutil.rmtree(directory)
    else:
        result["artifacts"] = str(directory)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--adapter", type=Path, help="adapter executable or Python script"
    )
    parser.add_argument(
        "--runner", type=Path, help="emulator executable, if the adapter needs one"
    )
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument(
        "--out", type=Path, default=Path("out/run"), help="new report directory"
    )
    parser.add_argument(
        "--case",
        action="append",
        default=[],
        metavar="PATTERN",
        help="select a name or quoted shell pattern; repeat to combine",
    )
    parser.add_argument(
        "--list", action="store_true", help="list selected cases without executing"
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30,
        metavar="SECONDS",
        help="wall time allowed per adapter invocation (default: 30)",
    )
    parser.add_argument(
        "--keep-passed", action="store_true", help="also retain successful observations"
    )
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout must be a positive finite number")
    fixtures = args.fixtures.resolve()
    manifest = load_manifest(fixtures)
    selected = select(manifest["cases"], args.case)
    if args.list:
        listing(selected)
        return
    if args.adapter is None:
        parser.error("--adapter is required for execution")
    adapter = args.adapter.resolve()
    command = (
        [sys.executable, str(adapter)] if adapter.suffix == ".py" else [str(adapter)]
    )
    source = sources(adapter, args.runner)
    if args.runner:
        command += ["--runner", str(args.runner.resolve())]
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    summary = {
        "source": source,
        "target": manifest["target"],
        "selection": args.case,
        "fixture_manifest_sha256": hashlib.sha256(
            (fixtures / "manifest.json").read_bytes()
        ).hexdigest(),
        "results": [],
    }
    try:
        capabilities = describe(command, out / "adapter", args.timeout)
        summary["adapter_capabilities"] = capabilities
        for case in selected:
            reasons = applicability(case, capabilities, manifest["target"], fixtures)
            if case["expectation"]["kind"] == "unresolved":
                outcome = {
                    "status": "unknown",
                    "failures": ["expectation is unresolved"],
                }
            elif reasons:
                outcome = {"status": "not_applicable", "failures": reasons}
            else:
                outcome = run_case(
                    case,
                    command,
                    fixtures,
                    manifest["eeprom"]["file"],
                    out / "cases" / case["name"],
                    args.timeout,
                    args.keep_passed,
                )
            result = {
                "case": case["name"],
                "expectation": case["expectation"],
                "conditions": case["conditions"],
                **outcome,
            }
            summary["results"].append(result)
            print(f"{result['status'].upper()} {case['name']}", flush=True)
            for failure in result["failures"]:
                print(f"  {failure}", flush=True)
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.TimeoutExpired,
    ) as error:
        summary["runner_error"] = str(error)
    finally:
        summary["source_unchanged"] = None
        try:
            after = sources(adapter, args.runner)
            summary["source_after"] = after
            if source != after:
                summary["source_unchanged"] = False
                summary["runner_error"] = (
                    summary.get("runner_error")
                    or "source or runner changed during execution"
                )
            elif (
                source["suite"]["tree_sha256"]
                and source["adapter"]["checkout"]["tree_sha256"]
            ):
                summary["source_unchanged"] = True
        except OSError as error:
            summary["runner_error"] = (
                summary.get("runner_error") or f"cannot recheck run sources: {error}"
            )
        summary["counts"] = {
            status: sum(r["status"] == status for r in summary["results"])
            for status in ["pass", "fail", "unknown", "not_applicable", "runner_error"]
        }
        write_json(out / "results.json", summary)
    print(f"Report: {out / 'results.json'}")
    counts = summary["counts"]
    if summary.get("runner_error"):
        raise SystemExit(summary["runner_error"])
    if counts["fail"] or counts["runner_error"]:
        raise SystemExit(1)
    if counts["unknown"] or counts["not_applicable"]:
        raise SystemExit(2)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise SystemExit(str(error))
