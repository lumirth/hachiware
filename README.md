# hachiware

Pokéwalker hardware diagnostics, independent of any emulator implementation.
Cases contain guest instructions, physical input timelines, and literal expected
observations derived from manuals or reasoned hardware behavior. The suite does
not import an emulator to calculate its answers.

```sh
python3 -m unittest discover -s tests
python3 build.py out/fixtures
python3 run.py --adapter ../hachistep-starter/tools/hachiware_adapter.py \
  --runner ../hachistep-starter/target/release/hachistep \
  --fixtures out/fixtures --report out/results.json
```

Python 3.10+ and its standard library are sufficient. Output paths must be new.
An adapter belongs with its emulator and translates observations into the small
contract below. A physical runner can implement the same contract where the
experiment is applicable.

The initial fifteen ROMs exercise register aliases, arithmetic flags, call/return,
RAM execution, aliased predecrement stores, EEPROM page wrap, infrared TX/RX,
Timer W capture, comparator wake, AEC overflow/gating, and NMI. The
`spec/register_access.tsv` table independently transcribes 95 physical access
widths and state counts from REJ09B0152-0300 §20.1. It is reference data for
diagnostics, not generated from a bus decoder.

Each manifest case identifies its target, input hashes, observation period,
question, expected results, and their basis. Existing cases are documented or
reasoned expectations; no physical captures are claimed. New observations should
cite the capture and its setup. Cases involving destructive flash or power-loss
experiments must say so before any physical runner executes them.

## Adapter contract

The runner invokes the adapter with these arguments:

```text
--runner EXECUTABLE --firmware FILE --eeprom FILE
--milliseconds INTEGER [--input CSV] --out NEW_DIRECTORY
```

The adapter runs the supplied guest to the exclusive requested endpoint and
exports `ram.bin` (2,048 bytes, base `0xf780`), `eeprom.bin` (65,536 bytes), and
`observations.json` with these hardware observations:

| Field | Meaning |
| --- | --- |
| `fault` | `null`, or a description of why guest execution stopped |
| `time_raw`, `requested_time_raw` | Decimal strings of unsigned 64.64 seconds |
| `time_us` | Truncated elapsed microseconds |
| `er` | Eight unsigned 32-bit CPU registers |
| `sleeping` | CPU sleep state |
| `interrupt_entries` | Accepted interrupt entries |
| `nv_commits` | Completed nonvolatile operations |
| `ir_events` | Infrared output transitions |
| `display_on`, `display_start` | LCD enable and start-line state |

Physical inputs use `time_us,kind,...` CSV rows: `ir,0|1`, `nmi,0|1`,
`digital,p10|p11|p12,0|1`, and `analog,pb0..pb5|vcref,millivolts|release`.
Adapters must preserve the stated timing and hardware meaning. They must never
patch instructions, replace firmware routines, or inject expected results.

The suite verifies input identity before execution and compares every requested
observation. Invalid paths, empty assertions, misspelled fields, and invalid
memory windows are rejected. Outcomes distinguish pass, fail, unknown
expectation, not applicable, and runner failure. Exit 0 means every case passed;
1 means a failure; 2 means incomplete applicability or expectations. The existing
manifest schema number is tooling metadata, unrelated to emulator save states.

The diagnostics were extracted from the approved HachiStep starter. Retail
firmware, private saves, and emulator-generated regression baselines remain
outside this suite.
