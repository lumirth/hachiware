# Hachiware

Hachiware benchmarks Pokéwalker emulators for hardware conformance and speed. It runs
original H8 guest programs against documented hardware behavior, then measures
representative use and sustained CPU, LCD, EEPROM, and infrared workloads.

Every speed appears beside its correctness result. Comparisons include raw timings for
targets that fail checks, so you can compare speed while seeing what still needs work.
The suite supports HachiStep and PocketWalker through adapters; other emulators and
physical test setups can implement the same [adapter contract](docs/adapter.md).

## Compare emulators

Use Python 3.10 or newer, or `uv run` to select `.python-version`. Build your emulator
executables first, then run:

```sh
uv run bench.py run --out out/bench-1 \
  --target hachistep ../hachistep/tools/hachiware_adapter.py ../hachistep/target/release/hachistep \
  --target pocketwalker adapters/pocketwalker/adapter.py ../pocketwalker-build/pw-hachiware
```

The report includes conformance scores, each workload's speed, and paired speed ratios.
`out/bench-1/results.json` retains the samples, seed, host, commands, and executable
identities. See the [benchmark guide](docs/benchmark.md) for PocketWalker setup,
workload selection, and scoring.

## Run diagnostics

```sh
uv run build.py out/fixtures --case 'adc-*'
uv run run.py --fixtures out/fixtures \
  --adapter ../hachistep/tools/hachiware_adapter.py \
  --runner ../hachistep/target/release/hachistep --out out/adc-1
```

Omit `--case` to build every diagnostic. Repeat a name or quoted pattern to combine
selections. `--list` shows purposes, sources, and conditions without running a target.
Use a new output directory for each command.

Failures retain observations and command logs under `cases/NAME/`; `--keep-passed`
also retains successful exports. A storage mismatch identifies the first differing
byte. Exit status is 0 for all passed, 1 for a failed check or runner, and 2 for
incomplete expectations or applicability.

## Add coverage

Keep original guest programs, literal expected results, conditions, and supporting
sources together. Expectations come from manuals, measurements, firmware evidence, or
stated inference. `--list` exposes those sources to the person running a case.

After changing a case or workload, execute it and run its control audit:

```sh
uv run bench.py audit --out out/audit-1 --case 'NAME*' --skip-workloads \
  --target hachistep ../hachistep/tools/hachiware_adapter.py ../hachistep/target/release/hachistep
```

Keep generated ROMs and reports under ignored `out/`. Behavioral coverage consists of
the guest diagnostics, workloads, and their controls. See [agent guidance](AGENTS.md)
for contribution constraints.

[MIT license](LICENSE).
