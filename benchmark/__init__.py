"""Benchmark workloads: firmware operating modes and hardware-block stress guests."""

from importlib import import_module

MODULES = ("pedometer", "ui", "ir", "buzzer", "cpu", "streams")


def workloads(seed: int):
    seen = set()
    for name in MODULES:
        for workload in import_module(f".workloads.{name}", __name__).workloads(seed):
            if workload.name in seen:
                raise ValueError(f"duplicate workload {workload.name}")
            seen.add(workload.name)
            yield workload
