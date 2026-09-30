# hachiware

Pokéwalker hardware diagnostics for emulators and physical test setups. Each case
contains an original guest program, any physical input timeline, and expected
observations supported by manuals, firmware evidence, measurements or inference.
Emulator adapters belong in their respective projects.

## Build and run

Use [uv](https://docs.astral.sh/uv/getting-started/installation/) to select the Python
version in `.python-version`. The tools use only the standard library and also run
with Python 3.10 or newer. The first uv invocation may download Python.

```sh
uv run build.py --list --case 'adc-*'
uv run build.py out/fixtures
uv run run.py --fixtures out/fixtures \
  --adapter ../hachistep-starter/tools/hachiware_adapter.py \
  --runner ../hachistep-starter/target/release/hachistep --out out/run-1
```

Pass `--case NAME` or a quoted pattern to build or run a selection. Repeat it to
combine selections. A pattern that matches nothing is an error. Both commands
support `--list`, which shows each selected case's purpose, sources and conditions
without executing it. Build an emulator executable separately before running cases.

Every output directory must be new. The runner writes `results.json`, records the
suite checkout, adapter and executable identities, and checks fixture hashes before
execution. Failures retain observations, stdout, stderr and the exact command under
`cases/NAME/` in the run directory. A storage mismatch reports the first differing
byte's address, expected and observed values, its offset within the expected block,
and the number of differing bytes. `--keep-passed` retains successful runs too.
`--timeout SECONDS` controls the wall time allowed for each adapter invocation.
These durations include process startup and export; use an emulator's benchmark tools
for performance measurements.

The runner records source and executable identities before and after execution. Checkout
fingerprints cover tracked and nonignored untracked contents, names, executable bits and
symlink targets. Keep generated outputs in ignored directories. A detected change fails
the run with `runner_error`; unavailable checkout fingerprints leave `source_unchanged`
null. Fingerprints do not archive the source or detect edits reverted between observations.
An executable hash does not establish which source built it.

Results distinguish `pass`, `fail`, `unknown`, `not_applicable` and `runner_error`.
Exit status 0 means every selected case passed, 1 means an assertion or runner failed,
and 2 means expectations or applicability were incomplete. Missing observations,
unsupported inputs and mismatched conditions explain why a case cannot run.

## Maintaining cases

`cases/` groups diagnostics by hardware mechanism. Keep each program's expected
observations, duration, conditions and explanation beside its definition. Share narrow
instruction encoders through `cases/h8.py`. A module can generate related cases from
a table. Register a new module in `cases/__init__.py`.

Arithmetic, multiplication and division cases store six-byte records starting at `0xf800`.
Each contains the big-endian ER0 result and two copies of CCR captured before stores
change it. The duplicate byte keeps every longword store at an even address.
Divide a reported block offset by six to find the record index, then follow the
case generator's operand order. A completion byte at `0xff20` distinguishes completed
programs from partially written results.

A `Case` records the program, expected values, optional input timeline, and evidence.
Use `conditions` for numerical assumptions that affect the result, such as the reset
circuit or battery sensing voltage drop. The runner compares these requirements with
the adapter's configured conditions before executing the case. An inference can support
a test; explain the mechanism and the circumstances in which its expectation applies.
A measurement must identify its capture and setup.

Keep diagnostic sources, literal expectations and curated reference data in Git.
`spec/register_access.tsv` transcribes access widths and state counts from the hardware
manual. Generated ROMs, manifests, reports and exploratory captures belong under ignored
`out/`. Preserve a hardware capture with its case when it becomes supporting reference
data, subject to its size and redistribution terms. Retail saves and an emulator's
regression baselines belong with that emulator's integration workflow.

After changing the builder or runner, run:

```sh
uv run -m unittest discover -s tests -v
```

After changing a case, rebuild its fixtures and run the affected selection through an
available adapter. Expected results must come from the case's stated evidence. A result
reported by the emulator under test cannot establish that emulator's hardware accuracy.

## Adapter contract

The runner first calls `ADAPTER [--runner EXECUTABLE] --describe`. A Python adapter
uses the runner's Python interpreter. Its stdout must contain a JSON object with:

- `target`: the target identifier, currently `H8/38606F` on the Pokéwalker board.
- `observations`: available storage and scalar fields from the table below.
- `inputs`: supported timeline inputs, such as `ir`, `supply` or `digital:p31`.
- `conditions`: configured quantities, using the names and units required by cases.

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
