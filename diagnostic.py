"""Diagnostic definitions, observation types and case selection."""

from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatchcase

TARGET = "H8/38606F"
KINDS = {"documented", "software_reasoned", "hardware_measured", "unresolved"}
COUNTS = {"nv_commits", "ir_events", "interrupt_entries"}
SCALARS = COUNTS | {"er0", "display_on", "display_start", "sleeping"}
STORAGE = {
    "ram": (0xF780, 2048),
    "eeprom": (0, 65536),
    "lcd": (0, 4096),
    "icons": (0, 256),
    "pixels": (0, 6144),
}


@dataclass(frozen=True)
class Case:
    name: str
    firmware: bytes
    expected: dict
    timeline: str | None = None
    evidence: dict = field(kw_only=True)
    milliseconds: int = field(default=8, kw_only=True)
    conditions: dict = field(default_factory=dict, kw_only=True)


def select(cases: list[dict], patterns: list[str]) -> list[dict]:
    """Each requested name or shell pattern must select at least one case."""
    for pattern in patterns:
        if not any(fnmatchcase(case["name"], pattern) for case in cases):
            raise ValueError(f"no cases match {pattern!r}")
    return [
        case
        for case in cases
        if not patterns
        or any(fnmatchcase(case["name"], pattern) for pattern in patterns)
    ]


def listing(cases: list[dict]) -> None:
    for case in cases:
        basis = case["expectation"]
        print(f"{case['name']} [{basis['kind']}, {case['milliseconds']} ms]")
        print(f"  {basis['question']}")
        print(f"  Source: {basis['source']}")
        if basis.get("limitation"):
            print(f"  Scope: {basis['limitation']}")
        if case.get("conditions"):
            print(
                "  Conditions: "
                + ", ".join(f"{k}={v}" for k, v in case["conditions"].items())
            )
        if basis.get("physical_device"):
            print(f"  Physical setup: {basis['physical_device']}")
