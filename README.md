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

The ROMs exercise register aliases, arithmetic flags, call/return,
RAM execution, aliased predecrement stores, EEPROM page wrap, infrared TX/RX,
SCI/GPIO optical routing, five-bit serial formats, error-byte/overrun handling,
and external synchronous transmit/receive,
Timer W capture, comparator wake, AEC overflow/gating, NMI, retained prefetch
under self-modification, division edge cases, direct clock transitions, and SSU
receive-only/overrun/holding-register behavior, EEPROM programming/reset,
LCD plane order, column reversal, partial duty, icons, and software reset,
and sensor address/data pairs and three-wire GPIO reads. A pulse/control pair
checks that analog response retains motion between conversion apertures. It uses
nominal startup/scan phase and asserts detection, without fixing Bosch damping
or a measured impulse amplitude. The image/shadow case allows analog settling
and masks the asynchronous freshness bit when comparing the subsequent pair.
The
RAM-resident flash cases cover control gating, delayed verify reads, error
protection, module wake, page programming with per-bit retry/strengthening masks,
and the target-specific EB4/EB5 erase geometry. They require explicit destructive
test authorization before use on a physical device; emulator execution has no
such physical effect. Pulse counts are never used as expected hardware results.
Boot cases drive ordinary 2400-baud RXD levels, upload original odd-length RAM
programs, and check baud/SCI/GPIO handoff plus six-block erasure. They also cover
invalid upload lengths using the stated containment inference.
Power cases distinguish suspended execution, RC reset with retained RAM, and
volatile loss during sustained undervoltage. Their manifest identifies the
nominal circuit and retention constants; they are calibration witnesses rather
than claims that every physical unit has those exact values.
The
`spec/register_access.tsv` table independently transcribes 95 physical access
widths and state counts from REJ09B0152-0300 §20.1. It is reference data for
diagnostics, not generated from a bus decoder.

Decimal-adjust guests sweep all 364 DAA and 380 DAS operand/H/C combinations
in the manufacturer tables with incoming N/Z clear and set. They mask undefined
H/V instead of locking in a particular ALU implementation. A separate arithmetic
case covers ADD/ADDX/SUB/SUBX/NEG and twenty valid carry states omitted by the
DAA table's printed ranges, with their basis labeled as decimal arithmetic.

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

Cases may also request `lcd.bin` (4,096 controller RAM bytes), `icons.bin`
(256 icon plane bytes, DB0 only), or `pixels.bin` (96×64 row-major logical
shade codes 0–3). These observations use physical controller layout and panel
bonding; pixel assertions do not prescribe analog luminance or a renderer.

Physical inputs use `time_us,kind,...` CSV rows: `ir,0|1`, `nmi,0|1`,
`digital,p10|p11|p12|p30|p31|p32|p90|p91|p92|p93|adtrg,0|1`, and
`analog,pb0..pb5|vcref,millivolts|release`.
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
