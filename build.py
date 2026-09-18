#!/usr/bin/env python3
"""Build or list original Pokéwalker diagnostics using Python's standard library."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from cases import cases
from diagnostic import TARGET, listing, select
from manifest import validate_case


def manifest_case(case) -> dict:
    return {
        "name": case.name,
        "firmware": f"{case.name}.bin",
        "sha256": hashlib.sha256(case.firmware).hexdigest(),
        "milliseconds": case.milliseconds,
        "expected": case.expected,
        "input": f"{case.name}.csv" if case.timeline else None,
        "input_sha256": hashlib.sha256(case.timeline.encode()).hexdigest()
        if case.timeline
        else None,
        "expectation": case.evidence,
        "conditions": case.conditions,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, nargs="?", help="new fixture directory")
    parser.add_argument(
        "--list", action="store_true", help="show cases, sources and conditions"
    )
    parser.add_argument(
        "--case",
        action="append",
        default=[],
        metavar="PATTERN",
        help="select a name or quoted shell pattern; repeat to combine",
    )
    args = parser.parse_args()
    generated = list(cases())
    guests = {case.name: case for case in generated}
    if len(guests) != len(generated):
        raise ValueError("duplicate diagnostic names")
    selected = select([manifest_case(case) for case in generated], args.case)
    for record in selected:
        validate_case(record)
    if args.list:
        listing(selected)
        return
    if args.output is None:
        parser.error("provide an output directory or --list")
    args.output.mkdir(parents=True, exist_ok=False)
    eeprom = bytes([255]) * 65536
    (args.output / "blank-eeprom.bin").write_bytes(eeprom)
    for record in selected:
        guest = guests[record["name"]]
        (args.output / record["firmware"]).write_bytes(guest.firmware)
        if guest.timeline:
            (args.output / record["input"]).write_bytes(guest.timeline.encode("utf-8"))
    manifest = {
        "target": TARGET,
        "eeprom": {
            "file": "blank-eeprom.bin",
            "sha256": hashlib.sha256(eeprom).hexdigest(),
        },
        "cases": selected,
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Built {len(selected)} diagnostics in {args.output}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        raise SystemExit(str(error))
