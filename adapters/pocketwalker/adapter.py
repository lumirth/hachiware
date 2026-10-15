#!/usr/bin/env python3
"""Run Hachiware through the PocketWalker bridge.

The bridge converts optical pulses to SCI3 bytes and advertises that input assist.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

OBSERVATIONS = [
    "ram", "eeprom", "lcd", "pixels", "er0", "sleeping", "display_start",
    "interrupt_entries", "ir_events",
]
INPUTS = ["buttons", "accel", "ir"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--describe", action="store_true")
    parser.add_argument("--runner", type=Path, help="pw-hachiware executable")
    parser.add_argument("--firmware", type=Path)
    parser.add_argument("--eeprom", type=Path)
    parser.add_argument("--milliseconds", type=int)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--observe", action="append", default=[], choices=OBSERVATIONS)
    args = parser.parse_args()
    if args.describe:
        print(json.dumps({
            "target": "H8/38606F",
            "observations": OBSERVATIONS,
            "inputs": INPUTS,
            "conditions": {},
            "assists": {
                "ir": "the bridge decodes optical pulses into SCI3 bytes at the bit rate "
                      "selected when each start pulse arrives and hands the core whole "
                      "bytes; the core has no IrDA receiver",
            },
        }, indent=2))
        return 0
    for field in ("runner", "firmware", "eeprom", "milliseconds", "out"):
        if getattr(args, field) is None:
            parser.error(f"--{field} is required for execution")
    command = [
        str(args.runner.resolve()), "--firmware", str(args.firmware.resolve()),
        "--eeprom", str(args.eeprom.resolve()), "--milliseconds", str(args.milliseconds),
        "--out", str(args.out.resolve()),
    ]
    if args.input:
        command += ["--input", str(args.input.resolve())]
    for field in args.observe:
        command += ["--observe", field]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    report = args.out / "observations.json"
    if result.returncode == 3:
        print(result.stderr, end="")
        return 3
    if result.returncode != 0 and not report.is_file():
        args.out.mkdir(parents=True, exist_ok=True)
        detail = (result.stdout + result.stderr).strip().splitlines()
        reason = detail[-1] if detail else f"exit status {result.returncode}"
        with report.open("x", encoding="utf-8") as stream:
            json.dump({"completed": False, "fault": f"emulator stopped: {reason}"}, stream)
            stream.write("\n")
        return 0
    print(result.stdout, end="")
    print(result.stderr, end="")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
