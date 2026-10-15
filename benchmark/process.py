"""Targets and timed adapter invocations."""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

import run as runner


class Target:
    """One emulator under test: a name, its adapter and an optional executable."""

    def __init__(self, name: str, adapter: Path, emulator: Path | None):
        self.name = name
        self.adapter = adapter.resolve()
        self.emulator = emulator.resolve() if emulator else None
        self.command = ([sys.executable, str(self.adapter)]
                        if self.adapter.suffix == ".py" else [str(self.adapter)])
        if self.emulator:
            self.command += ["--runner", str(self.emulator)]
        self.capabilities: dict = {}

    def sources(self) -> dict:
        return runner.sources(self.adapter, self.emulator)


def parse_targets(values) -> list[Target]:
    targets = []
    for value in values:
        if len(value) not in (2, 3):
            raise ValueError("--target takes NAME ADAPTER [EMULATOR]")
        targets.append(Target(value[0], Path(value[1]),
                              Path(value[2]) if len(value) == 3 else None))
    if len({t.name for t in targets}) != len(targets):
        raise ValueError("target names must be unique")
    return targets


def timed_invoke(command: list[str], directory: Path, timeout: float,
                 cpu: int | None) -> tuple[int, float, float]:
    """Run an adapter; return (status, wall seconds, CPU seconds of its process tree)."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "command.json").write_text(json.dumps(command))

    def prepare():
        os.setsid()
        if cpu is not None:
            os.sched_setaffinity(0, {cpu})

    with (directory / "stdout.log").open("wb") as out, \
            (directory / "stderr.log").open("wb") as err:
        started = time.perf_counter()
        process = subprocess.Popen(command, stdout=out, stderr=err, preexec_fn=prepare)
        expired = threading.Event()

        def kill():
            expired.set()
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

        timer = threading.Timer(timeout, kill)
        timer.start()
        try:
            _pid, status, usage = os.wait4(process.pid, 0)
        finally:
            timer.cancel()
        wall = time.perf_counter() - started
        process.returncode = os.waitstatus_to_exitcode(status)
    if expired.is_set():
        raise subprocess.TimeoutExpired(command, timeout)
    return process.returncode, wall, usage.ru_utime + usage.ru_stime
