# Connect an emulator

An adapter runs guests, delivers physical inputs, and exports observations in
hachiware's format. It lives with its emulator; hachiware includes the PocketWalker
adapter because the upstream project has none.

`bench.py` and `session.py` select an adapter with
`--target NAME ADAPTER EXECUTABLE`. The executable is optional when the adapter manages
its own runner. Python adapters execute with hachiware's Python interpreter.

## Describe capabilities

The runner first calls `ADAPTER [--runner EXECUTABLE] --describe`. Write one JSON
object to stdout. For example, an adapter exposing RAM and ER0 can report:

```json
{
  "target": "H8/38606F",
  "observations": ["ram", "er0"],
  "inputs": [],
  "conditions": {}
}
```

Advertise the observations and inputs the target supports. Cases name their required
conditions, and the runner checks those against the quantities declared here.
The description fields are:

- `target`: the target identifier, currently `H8/38606F` on the Pokéwalker board.
- `observations`: available storage and scalar fields from the table below.
- `inputs`: supported timeline inputs, such as `ir`, `supply` or `digital:p31`.
- `conditions`: configured quantities, using the names and units required by cases.
- `assists` (optional): an object mapping an input kind to a description of
  conversion work the adapter does in place of the emulator core, such as
  decoding optical pulses into bytes. Speed results of workloads using that input
  are reported as assisted and contribute to measured speed figures.

## Run a guest

A case executes with these arguments:

```text
[--runner EXECUTABLE] --firmware FILE --eeprom FILE
--milliseconds INTEGER [--input CSV] --out NEW_DIRECTORY
--observe FIELD [--observe FIELD ...]
```

The adapter applies timestamped inputs and completes the requested observation period.
The endpoint is exclusive. It creates `observations.json` with `completed: true`,
`fault: null`, and the requested scalar fields. A guest execution fault supplies a
`fault` description. An incomplete observation period is a runner error. The adapter
owns conversion to its emulator's clock representation and verifies completion using
that representation. For a completed run observing ER0, the JSON might be:

```json
{"completed": true, "fault": null, "er0": 0}
```

Storage observations go in the corresponding binary files below. Scalar observations
are fields in `observations.json`. Log diagnostic messages to stderr.

### Observation reference

| Observation | Representation |
| --- | --- |
| `ram` | `ram.bin`, 2,048 bytes starting at address `0xf780`. |
| `eeprom` | `eeprom.bin`, 65,536 bytes. |
| `lcd` | `lcd.bin`, 4,096 bytes in controller RAM order. |
| `icons` | `icons.bin`, 256 icon plane bytes with DB0 only. |
| `pixels` | `pixels.bin`, 96 by 64 averaged PWM/FRC drive values in row order. Scale the programmed palette duty to 0..255 and round to the nearest integer. Zero is inactive; 255 is full drive. Apply current RAM and geometry, without glass response or tint. |
| `lcd_supply` | `lcd_supply.bin`, seven little-endian `u32` microvolt values relative to VSS2: regulator target, pump, V0, V1, V2, V3, V4. `0xffffffff` marks a level not internally driven within documented operating conditions. |
| `lcd_drive` | `lcd_drive.bin`, 257 little-endian `u32` microvolt values relative to VSS2: COM0..128, then SEG0..127 at the observation endpoint. `0xffffffff` marks an unavailable level. |
| `er0` | Unsigned 32-bit CPU register value. |
| `sleeping`, `display_on` | Boolean values. |
| `display_start` | LCD start line from 0 to 127. |
| `interrupt_entries`, `nv_commits`, `ir_events` | Counts of accepted interrupts, completed nonvolatile operations, and optical output transitions. |

Export every requested observation from the advertised set.

### Physical input format

Input CSV rows use integer microsecond timestamps, with no header. `ir`, `nmi`,
`reset` and `power` take a 0 or 1; `supply` takes millivolts; `temperature` takes
millidegrees Celsius; `accel` takes three signed micro-g values including gravity;
`buttons` takes left, center and right pressed flags. `digital,PIN,VALUE` and
`analog,PIN,VALUE` drive package pins. Digital values are 0, 1 or `release`; analog
values are millivolts or `release`. Pin names and required inputs appear in each case.
An adapter advertises pin inputs individually, for example `analog:pb4`.

## Support firmware sessions

An adapter can advertise a `sessions` list with `capture`, `history`, `chunk`,
`edit_ram`, `audio` and `link`. The session runner uses the same invocation as a case,
with `--session` and the following operations:

| Argument | Operation |
| --- | --- |
| `--load-state FILE` | Resume a capture instead of supplying firmware and EEPROM. Horizons and input timestamps remain absolute. |
| `--history` | Record the complete event history. |
| `--chunk-us N` | Bound individual host execution calls to N microseconds. |
| `--write-ram ADDRESS:HEX` | Edit guest RAM before execution. Repeatable; ADDRESS is hexadecimal. |
| `--audio` | Export `audio.wav` as mono 48 kHz signed PCM16. |
| `--peer-eeprom FILE --peer-input CSV --delay-us N` | Run a second device with the same firmware, exchanging optical levels with N microseconds of propagation delay. Export its observations under `peer/`. |

The horizon can be zero for initial inspection. The adapter writes `session.json`:

- `fault`: a description or null.
- `start_raw`, `end_raw`, `requested_raw`: decimal strings in unsigned 64.64 seconds.
- `observations`: final scalar observations, including `display_contrast` for gameplay.
- `artifacts`: observation names mapped to simple filenames, including an opaque
  `state` capture. Contents must support byte-for-byte comparisons of equivalent runs.
- `counters`: interval counts for `interrupt_entries`, `nv_commits`, `ir_events` and
  `buzzer_events`.
- `history`: `path`, `complete` and `records`. Each record occupies one line; its
  contents are adapter-owned. A resumed history must concatenate with its prefix to
  reproduce continuous execution.
- `run_seconds`: wall time spent executing the device, excluding startup and exports.

A linked run also writes `peer/session.json`. Adapters own invocation details and native
file formats. Session definitions and checks remain in hachiware.

## Exercise the adapter

Run a [diagnostic](diagnostics.md) and its
[control audit](contributing.md#check-that-the-experiment-detects-wrong-behavior)
to check guest execution and exports. The
[short firmware sessions](sessions.md#start-with-the-short-sessions) exercise
capture and history.
