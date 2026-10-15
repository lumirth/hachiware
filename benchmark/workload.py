"""Speed workloads: a guest, its inputs, and a check of each observed run.

A workload is built from a seed. The seed chooses the guest's data, its inputs
and the placement of its code, so expected results cannot be computed ahead of
a run and repeated work is not repeated data. Every run of a workload is
checked against expectations computed here from the guest's definition and
the hardware documentation, never from an emulator. A run whose observations
differ is inaccurate and its time does not count.

Workloads observe only memory: CPU RAM, EEPROM, LCD RAM and the LCD start line.
Every adapter can export those, so every emulator runs every workload on
equal terms.

Two shapes cover all workloads:

- ``paced``: the guest repeats a pass at a fixed period set by a hardware
  time base, and is observed in the middle of a pass at
  ``setup + n * period + period / 2``. The expected state depends only on how
  many passes have completed.
- free-running: the guest never waits. It numbers its work items and keeps
  the results of the last few; ``check`` reads the item count from RAM and
  verifies those results, and timing witnesses bound how fast items may
  complete.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from diagnostic import STORAGE

TIERS = ("use", "hardware")
OBSERVABLE = ("ram", "eeprom", "lcd", "display_start")


@dataclass(frozen=True)
class Workload:
    name: str
    tier: str
    summary: str
    blocks: tuple[str, ...]
    evidence: dict
    image: bytes
    horizons: tuple[int, ...]  # Increasing run lengths in ms; the first is the timing base.
    check: Callable[[int, dict], list[str]]  # (horizon ms, observations) -> failures
    observe: tuple[str, ...]
    units: Callable[[int], dict]  # Work units completed by a horizon, for ns/unit.
    eeprom: bytes | None = None
    timeline: Callable[[int], str] | None = None  # Inputs up to a horizon in ms.
    inputs: tuple[str, ...] = ()
    seed: int = 0

    def __post_init__(self):
        if self.tier not in TIERS:
            raise ValueError(f"{self.name}: unknown tier {self.tier}")
        if len(self.image) != 49152:
            raise ValueError(f"{self.name}: firmware must be 48 KiB")
        if self.eeprom is not None and len(self.eeprom) != 65536:
            raise ValueError(f"{self.name}: EEPROM must be 64 KiB")
        if list(self.horizons) != sorted(set(self.horizons)) or len(self.horizons) < 2:
            raise ValueError(f"{self.name}: horizons must increase")
        if set(self.observe) - set(OBSERVABLE) or "ram" not in self.observe:
            raise ValueError(f"{self.name}: workloads observe RAM and other memory only")
        for key in ("kind", "source", "question"):
            if not self.evidence.get(key):
                raise ValueError(f"{self.name}: evidence needs {key}")


def u32(value: int) -> str:
    return (value & 0xFFFFFFFF).to_bytes(4, "big").hex()


def u16(value: int) -> str:
    return (value & 0xFFFF).to_bytes(2, "big").hex()


def compare_memory(expected: dict, observed: dict) -> list[str]:
    """Compare expected hex blocks and scalars with exported observations."""
    failures = []
    for domain, (start, _size) in STORAGE.items():
        data = observed.get(domain)
        for address, text in expected.get(domain, {}).items():
            if data is None:
                failures.append(f"{domain} not exported")
                break
            offset = int(address, 16) - start
            wanted = bytes.fromhex(text)
            actual = data[offset:offset + len(wanted)]
            if actual != wanted:
                diffs = [i for i in range(len(wanted))
                         if i >= len(actual) or actual[i] != wanted[i]]
                first = diffs[0]
                got = f"{actual[first]:02x}" if first < len(actual) else "nothing"
                failures.append(
                    f"{domain}[{start + offset + first:04x}]: expected {wanted[first]:02x}, "
                    f"got {got}; {len(diffs)} of {len(wanted)} bytes differ in block {address}")
    for key, value in expected.items():
        if key in STORAGE:
            continue
        if observed.get(key) != value:
            failures.append(f"{key}: expected {value!r}, got {observed.get(key)!r}")
    return failures


def read(observed: dict, address: int, size: int) -> int:
    offset = address - STORAGE["ram"][0]
    return int.from_bytes(observed["ram"][offset:offset + size], "big")


def check_witnesses(witnesses: dict, observed: dict) -> list[str]:
    failures = []
    for name, (address, size, low, high) in witnesses.items():
        value = read(observed, address, size)
        if not low <= value <= high:
            failures.append(f"witness {name}: measured {value}, expected {low}..{high}")
    return failures


@dataclass(frozen=True)
class Paced:
    """Expectations of a paced guest as functions of completed passes."""

    period_ms: int
    setup_ms: int
    passes: tuple[int, ...]
    expected: Callable[[int], dict]
    witnesses: Callable[[int], dict] = field(default=lambda n: {})
    units: Callable[[int], dict] = field(default=lambda n: {"passes": n})

    def horizon(self, n: int) -> int:
        return self.setup_ms + n * self.period_ms + self.period_ms // 2

    def passes_at(self, horizon: int) -> int:
        n = (horizon - self.setup_ms - self.period_ms // 2) // self.period_ms
        if self.horizon(n) != horizon:
            raise ValueError(f"{horizon} ms is not a pass midpoint")
        return n

    def check(self, horizon: int, observed: dict) -> list[str]:
        n = self.passes_at(horizon)
        return (compare_memory(self.expected(n), observed)
                + check_witnesses(self.witnesses(n), observed))

    def fields(self) -> dict:
        return {
            "horizons": tuple(self.horizon(n) for n in self.passes),
            "check": self.check,
            "units": lambda h: self.units(self.passes_at(h)),
        }


def observed_fields(expected: dict) -> tuple[str, ...]:
    return tuple(sorted({"ram", *expected}))
