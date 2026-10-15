# Adapter contract

The runner first calls `ADAPTER [--runner EXECUTABLE] --describe`. A Python adapter
uses the runner's Python interpreter. Its stdout must contain a JSON object with:

- `target`: the target identifier, currently `H8/38606F` on the Pokéwalker board.
- `observations`: available storage and scalar fields from the table below.
- `inputs`: supported timeline inputs, such as `ir`, `supply` or `digital:p31`.
- `conditions`: configured quantities, using the names and units required by cases.
- `assists` (optional): an object mapping an input kind to a description of
  conversion work the adapter does in place of the emulator core, such as
  decoding optical pulses into bytes. Speed results of workloads using that input
  are reported as assisted and never verified.

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
that representation.

| Observation | Representation |
| --- | --- |
| `ram` | `ram.bin`, 2,048 bytes starting at address `0xf780`. |
| `eeprom` | `eeprom.bin`, 65,536 bytes. |
| `lcd` | `lcd.bin`, 4,096 bytes in controller RAM order. |
| `icons` | `icons.bin`, 256 icon plane bytes with DB0 only. |
| `pixels` | `pixels.bin`, 96 by 64 averaged PWM/FRC drive values in row order. Scale the programmed palette duty to 0..255 and round to the nearest integer. Zero is inactive; 255 is full drive. Apply current RAM and geometry, without glass response or tint. |
| `er0` | Unsigned 32-bit CPU register value. |
| `sleeping`, `display_on` | Boolean values. |
| `display_start` | LCD start line from 0 to 127. |
| `interrupt_entries`, `nv_commits`, `ir_events` | Counts of accepted interrupts, completed nonvolatile operations, and optical output transitions. |

Only requested observations are required. An adapter can declare the subset it can
observe. Physical runners need a way to retrieve those results after measurement and
must enforce any destructive experiment restrictions recorded with the case.

Input CSV rows use integer microsecond timestamps, with no header. `ir`, `nmi`,
`reset` and `power` take a 0 or 1; `supply` takes millivolts; `temperature` takes
millidegrees Celsius; `accel` takes three signed micro-g values including gravity;
`buttons` takes left, center and right pressed flags. `digital,PIN,VALUE` and
`analog,PIN,VALUE` drive package pins. Digital values are 0, 1 or `release`; analog
values are millivolts or `release`. Pin names and required inputs appear in each case.
An adapter advertises pin inputs individually, for example `analog:pb4`.
