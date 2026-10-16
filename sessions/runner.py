"""Run sessions through adapters; compare observations and opaque captures."""
from __future__ import annotations

from dataclasses import dataclass
import itertools
import json
from pathlib import Path

import run as runner
from benchmark.process import timed_invoke


@dataclass
class Observation:
    directory: Path
    report: dict

    def artifact(self, name):
        filename = self.report["artifacts"][name]
        if Path(filename).name != filename:
            raise ValueError("session artifacts must be simple filenames")
        return self.directory / filename

    def data(self, name):
        return self.artifact(name).read_bytes()

    def history(self):
        history = self.report["history"]
        if history["complete"] is not True:
            raise ValueError("session needs a complete event history")
        filename = history["path"]
        if Path(filename).name != filename:
            raise ValueError("history must be a simple filename")
        count = 0
        with (self.directory / filename).open("rb") as stream:
            for record in stream:
                count += 1
                yield record
        if count != history["records"]:
            raise ValueError("history record count differs from its report")


def compare(whole: Observation, final: Observation, prefix: Observation | None = None,
            *, history=True) -> list[str]:
    errors = []
    a, b = whole.report, final.report
    if a["end_raw"] != b["end_raw"] or a["observations"] != b["observations"]:
        errors.append("final time or observations differ")
    if prefix:
        if a["start_raw"] != prefix.report["start_raw"] or prefix.report["end_raw"] != b["start_raw"]:
            errors.append("captured intervals do not cover the continuous session")
    elif a["start_raw"] != b["start_raw"] or a["counters"] != b["counters"]:
        errors.append("initial time or execution counters differ")
    if a["artifacts"].keys() != b["artifacts"].keys():
        errors.append("artifact sets differ")
    else:
        for name in a["artifacts"]:
            if runner.identity(whole.artifact(name))["sha256"] != runner.identity(final.artifact(name))["sha256"]:
                errors.append(f"{name}: final bytes differ")
    if history:
        restored = (itertools.chain(prefix.history(), final.history()) if prefix else final.history())
        first = None
        # Exhaust both streams even after a mismatch to validate their counts.
        for index, (left, right) in enumerate(itertools.zip_longest(whole.history(), restored)):
            if first is None and left != right:
                first = index
        if first is not None:
            errors.append(f"event history differs at record {first}")
    return errors


class SessionRunner:
    def __init__(self, target, output: Path, timeout=900):
        self.target, self.output, self.timeout = target, output, timeout
        self.records = []
        target.capabilities = runner.describe(target.command, output / "describe", timeout)
        self.sources = target.sources()
        self.require("capture", "history")

    def require(self, *capabilities):
        missing = set(capabilities) - set(self.target.capabilities.get("sessions", []))
        if missing:
            raise ValueError(f"{self.target.name}: missing session capabilities: {', '.join(sorted(missing))}")

    def execute(self, name, milliseconds, *, firmware=None, eeprom=None, inputs=None,
                restore=None, history=True, chunk_us=None, edits=(), audio=False,
                peer_eeprom=None, peer_input=None, delay_us=1):
        if restore:
            self.require("capture")
        if chunk_us:
            self.require("chunk")
        if edits:
            self.require("edit_ram")
        if audio:
            self.require("audio")
        if peer_eeprom:
            self.require("link")
        directory = self.output / name
        output = directory / "observations"
        initial = (["--load-state", str(restore.resolve())] if restore else
                   ["--firmware", str(firmware.resolve()), "--eeprom", str(eeprom.resolve())])
        command = [*self.target.command, "--session", *initial,
                   "--milliseconds", str(milliseconds), "--out", str(output)]
        if history:
            command += ["--history"]
        if inputs:
            command += ["--input", str(inputs.resolve())]
        if chunk_us:
            command += ["--chunk-us", str(chunk_us)]
        for at, data in edits:
            command += ["--write-ram", f"{at:04x}:{data.hex()}"]
        if audio:
            command += ["--audio"]
        if peer_eeprom:
            command += ["--peer-eeprom", str(peer_eeprom.resolve()), "--delay-us", str(delay_us)]
            if peer_input:
                command += ["--peer-input", str(peer_input.resolve())]
        status, wall, cpu = timed_invoke(command, directory, self.timeout, None)
        record = {"name": name, "command": command, "status": status,
                  "process_wall_seconds": wall, "process_cpu_seconds": cpu}
        self.records.append(record)
        if status:
            raise RuntimeError(f"{name}: adapter failed; see {directory}")
        report = json.loads((output / "session.json").read_text())
        expected = str((milliseconds << 64) // 1000)
        if report["fault"] is not None or report["end_raw"] != expected or report["requested_raw"] != expected:
            raise ValueError(f"{name}: fault or incomplete session")
        record["run_seconds"] = report["run_seconds"]
        return Observation(output, report)

    def unchanged(self):
        return self.target.sources() == self.sources
