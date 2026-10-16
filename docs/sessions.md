# Firmware sessions

Run supplied firmware and EEPROM images through scripted sessions:

```sh
uv run session.py --firmware firmware.bin --eeprom eeprom.bin --quick --chunk-us 1000 \
  --out out/sessions-1 \
  --target hachistep ../hachistep/tools/hachiware_adapter.py ../hachistep/target/release/hachistep
```

`--list` lists sessions without loading images. `--quick` selects home, menu and
settings. Repeat `--case NAME` to select others, including walking, interrupted saves,
connection timeout and a day rollover. Timelines and checkpoints live in
[`sessions/retail/`](../sessions/retail/).

Each session must reach its horizon. Checkpoints compare the continuous run with a
saved and restored continuation, including exported observations, opaque machine state
and the complete event history. `--chunk-us` also compares shorter host calls with a
continuous run. These comparisons establish reproducibility.

`--play` additionally checks walking, Dowsing and a capture, including charges and
rewards saved to EEPROM, audible output, display state and restoration during gameplay.
`--link` connects two firmware instances through a one-microsecond optical channel and
checks that each commits the other's identity to encounter history. Both require the
matching retail firmware and an EEPROM containing a walking Pokemon. The suite prepares
copies of the supplied save. Firmware-specific layouts and assertions follow
[`pw` at 6dc7bc0](https://github.com/lumirth/pw/tree/6dc7bc09950078fa3fe0dffa4dae34e9549a99da).

## Compare builds and host cost

Repeat `--target` to compare builds. The session runner compares each build's complete
observations, state and event history with the first target. Opaque state comparisons
require compatible save-state formats.

Add `--measure --samples 3` to measure the selected sessions after verification. Target
order alternates between samples. Reports retain end-to-end wall and process-tree CPU
time, plus the adapter's execution time. End-to-end measurements include process
startup, image loading and final exports. Use `--chunk-us` to measure call-horizon cost.
For sustained throughput, use the [benchmark runner](benchmark.md).

Every output directory must be new. `results.json` records source and input identities,
commands, comparisons and raw timing samples. Each run retains its observations and
logs. The adapter contract describes the [session operations](adapter.md#sessions).
