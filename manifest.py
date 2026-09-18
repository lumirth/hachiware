"""Validate diagnostic inputs and expected observations before execution."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
import re

from diagnostic import KINDS, SCALARS, STORAGE


def checked_file(
    root: Path, name: str, expected_hash: str, size: int | None = None
) -> Path:
    if not isinstance(name, str) or Path(name).name != name or name in {"", ".", ".."}:
        raise ValueError("fixture members must be simple filenames")
    path = root / name
    if path.resolve().parent != root.resolve():
        raise ValueError("fixture member escapes its directory")
    data = path.read_bytes()
    if size is not None and len(data) != size:
        raise ValueError(f"{name}: expected {size} bytes, got {len(data)}")
    if hashlib.sha256(data).hexdigest() != expected_hash:
        raise ValueError(f"{name}: fixture SHA-256 mismatch")
    return path


def validate_expected(expected: dict) -> None:
    if not isinstance(expected, dict) or expected.keys() - (SCALARS | STORAGE.keys()):
        raise ValueError("unknown or malformed expected-result key")
    for domain, (start, length) in STORAGE.items():
        entries = expected.get(domain, {})
        if not isinstance(entries, dict):
            raise ValueError(f"{domain}: expectations must map addresses to hex bytes")
        for address, text in entries.items():
            if (
                not isinstance(address, str)
                or re.fullmatch("[0-9a-fA-F]{4}", address) is None
            ):
                raise ValueError(f"{domain}: invalid address")
            if (
                not isinstance(text, str)
                or re.fullmatch("(?:[0-9a-fA-F]{2})+", text) is None
            ):
                raise ValueError(f"{domain}: expected nonempty hex bytes")
            offset = int(address, 16) - start
            if not 0 <= offset <= length - len(bytes.fromhex(text)):
                raise ValueError(f"{domain}: expected range outside physical storage")
            if domain == "pixels" and any(shade > 3 for shade in bytes.fromhex(text)):
                raise ValueError("pixels: expected two-bit shade codes")
    for key in expected.keys() & SCALARS:
        value = expected[key]
        if key in {"display_on", "sleeping"}:
            if type(value) is not bool:
                raise ValueError(f"{key}: expected Boolean")
        elif type(value) is not int or value < 0:
            raise ValueError(f"{key}: expected nonnegative integer")
        if key == "er0" and value > 0xFFFFFFFF:
            raise ValueError("ER0 does not fit 32 bits")
        if key == "display_start" and value > 127:
            raise ValueError("display start does not fit seven bits")


def validate_case(case: dict) -> None:
    if not isinstance(case, dict):
        raise ValueError("each diagnostic must be an object")
    name = case["name"]
    if not isinstance(name, str) or re.fullmatch("[a-z0-9-]+", name) is None:
        raise ValueError("invalid fixture identifier")
    milliseconds = case["milliseconds"]
    if type(milliseconds) is not int or not 1 <= milliseconds <= 120000:
        raise ValueError("diagnostic duration must be 1..120000 ms")
    basis = case["expectation"]
    if not isinstance(basis, dict):
        raise ValueError("expectation must describe its basis")
    if (
        basis.get("kind") not in KINDS
        or not basis.get("question")
        or not basis.get("source")
    ):
        raise ValueError("missing expectation provenance/question")
    if basis["kind"] == "hardware_measured" and not basis.get("observation_id"):
        raise ValueError(
            "a hardware expectation must identify its captured observation"
        )
    conditions = case["conditions"]
    if not isinstance(conditions, dict) or any(
        not isinstance(key, str)
        or not key
        or type(value) not in (str, int, float, bool)
        or isinstance(value, float)
        and not math.isfinite(value)
        for key, value in conditions.items()
    ):
        raise ValueError("conditions must name finite numbers, strings or Booleans")
    validate_expected(case["expected"])
    assertions = any(
        key in SCALARS or bool(value) for key, value in case["expected"].items()
    )
    if not assertions and basis["kind"] != "unresolved":
        raise ValueError("an established test must make an assertion")


def load_manifest(fixtures: Path) -> dict:
    manifest = json.loads((fixtures / "manifest.json").read_text())
    if not isinstance(manifest, dict):
        raise ValueError("fixture manifest must be an object")
    if not isinstance(manifest.get("target"), str) or not manifest["target"]:
        raise ValueError("missing fixture target")
    eeprom = manifest["eeprom"]
    checked_file(fixtures, eeprom["file"], eeprom["sha256"], 65536)
    cases = manifest["cases"]
    if not isinstance(cases, list) or not cases:
        raise ValueError("empty or malformed fixture corpus")
    names = set()
    for case in cases:
        validate_case(case)
        name = case["name"]
        if name in names:
            raise ValueError("duplicate or unsafe fixture identifier")
        names.add(name)
        checked_file(fixtures, case["firmware"], case["sha256"], 49152)
        if case.get("input") is not None:
            checked_file(fixtures, case["input"], case["input_sha256"])
        elif case.get("input_sha256") is not None:
            raise ValueError("timeline hash supplied without a timeline")
    return manifest


def required_inputs(path: Path | None) -> set[str]:
    if path is None:
        return set()
    required = set()
    with path.open(encoding="utf-8", newline="") as stream:
        for row in csv.reader(stream):
            row = [value.strip() for value in row]
            if not row or row[0].lstrip().startswith("#"):
                continue
            if len(row) < 3 or not row[0].isdigit():
                raise ValueError("malformed input timeline row")
            kind = row[1]
            required.add(f"{kind}:{row[2]}" if kind in {"analog", "digital"} else kind)
    return required
