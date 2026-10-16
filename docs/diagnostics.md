# Investigate hardware behavior

Each diagnostic runs an H8 guest and compares its observations with an expected
hardware result. The case keeps its question, source evidence, and required
conditions beside the program.

Use Python 3.10 or newer on Linux or macOS. Build your emulator and its adapter first;
the [benchmark setup](benchmark.md#set-up-the-targets) includes hachistep and PocketWalker.
Run the following commands from the hachiware checkout.

## Find a case

List the ADC cases with their sources and conditions:

```sh
uv run build.py --list --case 'adc-*'
```

Omit `--case` to list all diagnostics. Select exact names or quoted shell patterns;
repeat `--case` to combine selections.

## Run the selected diagnostics

Build the guest images and run them through hachistep's adapter:

```sh
uv run build.py out/adc-fixtures --case 'adc-*'
uv run run.py --fixtures out/adc-fixtures \
  --adapter ../hachistep/tools/hachiware_adapter.py \
  --runner ../hachistep/target/release/hachistep --out out/adc-results
```

Substitute another adapter and executable to use another emulator. The fixtures contain
original diagnostic firmware, a blank EEPROM image, and the required input timelines.
Each output directory must be new.

For a whole-suite result grouped by hardware feature, use the benchmark runner:

```sh
uv run bench.py run --skip-workloads --out out/diagnostics \
  --target hachistep ../hachistep/tools/hachiware_adapter.py ../hachistep/target/release/hachistep
```

## Inspect a failure

The standalone runner prints `PASS`, `FAIL`, or `RUNNER_ERROR` for each case and writes
`results.json`. Failed cases retain their command, stdout, stderr, and exported
observations under `cases/NAME/`. Storage comparisons identify the first differing byte.
Add `--keep-passed` to `run.py` to retain successful captures too.

`RUNNER_ERROR` means the runner could not obtain the required observations.
Inspect the command and logs for a launch failure, timeout, incomplete endpoint,
or missing export. The [adapter reference](adapter.md) defines completion.

Standalone exit status is 0 when all selected cases pass, 1 for a failed check or runner,
and 2 for incomplete expectations or applicability. Required board conditions appear
in `--list`; the runner compares them with the adapter's declared conditions.

## Read the evidence

A `documented` expectation follows a cited manual, erratum, or other explicit source.
A `software_reasoned` expectation records an interpretation derived from available
sources. `hardware_measured` identifies a retained physical observation. An `unresolved`
case records a question without an established expectation and contributes no score.
The listing shows the evidence and any conditions for each case.

[Adding diagnostics and checking their controls](contributing.md).
