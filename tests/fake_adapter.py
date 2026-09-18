"""Adapter fixture for testing result handling without an emulator."""

import argparse
import json
from pathlib import Path
import time

parser = argparse.ArgumentParser()
parser.add_argument("--describe", action="store_true")
parser.add_argument("--runner", type=Path, required=True)
parser.add_argument("--firmware")
parser.add_argument("--eeprom")
parser.add_argument("--milliseconds")
parser.add_argument("--input")
parser.add_argument("--observe", action="append")
parser.add_argument("--out", type=Path)
args = parser.parse_args()
config = json.loads(args.runner.read_text())
if args.describe:
    print(json.dumps(config["capabilities"]))
else:
    args.out.mkdir()
    print("adapter stdout", flush=True)
    import sys

    print("adapter stderr", file=sys.stderr, flush=True)
    time.sleep(config.get("sleep", 0))
    if config.get("report") is not None:
        (args.out / "observations.json").write_text(json.dumps(config["report"]))
    if config.get("change_runner"):
        args.runner.write_text("changed during execution")
    raise SystemExit(config.get("returncode", 0))
