<img src="docs/images/icon.svg" alt="hachiware" width="128">

# hachiware

hachiware is a hardware diagnostic and benchmarking suite for Pokéwalker emulators.
It is the sister project of [hachistep](https://github.com/lumirth/hachistep),
an accurate and performant Pokéwalker emulator core.

[Benchmark emulators](docs/benchmark.md) ·
[Run diagnostics](docs/diagnostics.md) · [Run firmware sessions](docs/sessions.md)

## Explore the diagnostics

With Python 3.10 or newer, list the ADC cases and their sources:

```sh
uv run build.py --list --case 'adc-*'
```
