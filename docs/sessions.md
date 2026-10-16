# Run firmware sessions

Firmware sessions compare uninterrupted execution with restored and chunked runs,
including captures during EEPROM writes. Gameplay and peer checks inspect results
committed to EEPROM.

## Start with the short sessions

Build hachistep using the [target setup](benchmark.md#set-up-the-targets). Supply a raw
49,152-byte retail firmware image and a 65,536-byte EEPROM image. Run from the hachiware
checkout, replacing the image paths:

```sh
uv run session.py --firmware /path/to/firmware.bin --eeprom /path/to/eeprom.bin \
  --quick --chunk-us 1000 --out out/sessions \
  --target hachistep ../hachistep/tools/hachiware_adapter.py ../hachistep/target/release/hachistep
```

`--quick` runs home, menu, and settings. Successful sessions print `PASS` and leave
captures and `results.json` under `out/sessions`. The settings session also resumes
from a checkpoint during a save. `--chunk-us 1000` repeats each session with host calls
bounded to one millisecond and compares the result with continuous execution.

Every session must reach its endpoint with matching machine state and observations.
The event histories before and after a capture must concatenate to reproduce the
uninterrupted history.

## Select longer sessions

```sh
uv run session.py --list
```

The listing gives durations and timelines. Omit `--quick` to run all sessions, or
repeat `--case NAME` to select individual ones. Selections include walking, idle,
interrupted primary and backup saves, connection timeout, and a day rollover.

Capture points fall during saves, a connection attempt, or the RTC update before
midnight. Settings and interrupted-save expectations follow
[`pw_local_settings.c`](https://github.com/lumirth/pw/blob/6dc7bc09950078fa3fe0dffa4dae34e9549a99da/src/application/pw_local_settings.c)
and [`pw_eeprom_m95512_io.c`](https://github.com/lumirth/pw/blob/6dc7bc09950078fa3fe0dffa4dae34e9549a99da/src/application/pw_eeprom_m95512_io.c).

## Check gameplay and peer exchange

Add `--play` to check Watts earned by walking, Dowsing and radar charges, saved rewards,
audible output, display state, and restoration during gameplay. Add `--link` to run
two devices through a one-microsecond optical channel and check that each saves the
other's identity in encounter history.

Both options require the matching retail firmware and an EEPROM with a walking
Pokémon. The suite prepares copies of that save for the experiment. Save layouts and
expected results follow the [matching `pw` reconstruction](https://github.com/lumirth/pw/tree/6dc7bc09950078fa3fe0dffa4dae34e9549a99da).
The adapter must support the requested [session operations](adapter.md#support-firmware-sessions).

For example, extend the short run with both checks:

```sh
uv run session.py --firmware /path/to/firmware.bin --eeprom /path/to/eeprom.bin \
  --quick --play --link --chunk-us 1000 --out out/gameplay \
  --target hachistep ../hachistep/tools/hachiware_adapter.py ../hachistep/target/release/hachistep
```

## Compare builds

Repeat `--target` with another name, adapter, and executable. The runner compares each
target's observations, state, and history with the first target. Use builds with
compatible state formats because the comparison includes their encoded captures.
For example, a native hachistep CLI and a WASI CLI from the same revision can be
compared through the same adapter. The WASI run also needs Wasmtime installed.

`--scenarios FILE` selects the session definition and associated input timelines for
all targets in the comparison.

## Measure complete sessions

Add `--measure --samples 3` to time selected sessions after verification. Reports give
end-to-end wall time, process-tree CPU time, and the adapter's device execution time.
End-to-end time includes startup, image loading, and final exports. Target order
alternates between samples, and timed captures must match the verified result.

Use `--chunk-us` to include the cost of short execution calls. For sustained throughput
with startup and exports removed, use the [benchmark runner](benchmark.md).

Choose a new output directory for every run. `results.json` retains source and input
identities, commands, comparisons, and timing samples. Each run keeps its observations
and logs. Keep images, sources, and executables unchanged while it runs.
