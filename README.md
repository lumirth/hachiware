<img src="docs/images/icon.svg" alt="hachiware" width="128">

# hachiware

hachiware is a hardware diagnostic and benchmarking suite for Pokéwalker emulators.
Its guest programs pair hardware experiments with expected results and the evidence
behind them. The same experiments run across emulators through adapters.

The benchmark report shows every workload's speed beside its correctness result,
including speeds for workloads that fail. Firmware sessions check saved-state
continuation, gameplay, and peer exchange.

[Compare hachistep and PocketWalker](docs/benchmark.md) ·
[Run diagnostics](docs/diagnostics.md) · [Run firmware sessions](docs/sessions.md)

## Explore the diagnostics

With Python 3.10 or newer, list the ADC cases and their sources:

```sh
uv run build.py --list --case 'adc-*'
```
