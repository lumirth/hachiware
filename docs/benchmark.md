# Compare emulator accuracy and speed

Compare hachistep and PocketWalker on the same generated guest images. The report
shows each workload's speed and correctness result, plus head-to-head ratios.

## Set up the targets

Use Linux or macOS with Python 3.10 or newer. The commands use `uv run` to select
hachiware's configured Python version. You also need Rust 1.95 or newer for hachistep,
CMake 3.20 or newer, and a C++23 compiler for PocketWalker.

Clone the three projects beside one another:

```sh
git clone https://github.com/lumirth/hachiware.git
git clone https://github.com/lumirth/hachistep.git
git clone https://github.com/h4lfheart/pocketwalker.git
cd hachiware
```

Build hachistep's CLI and hachiware's PocketWalker runner:

```sh
cargo build --manifest-path ../hachistep/Cargo.toml -p hs-cli --release --locked
cmake -S adapters/pocketwalker -B ../pocketwalker-build \
  -DPW_ROOT="$PWD/../pocketwalker" -DCMAKE_BUILD_TYPE=Release
cmake --build ../pocketwalker-build
```

The PocketWalker runner uses the upstream core's desktop release settings.
For existing checkouts, adjust the paths.

## Run a comparison

From the hachiware checkout:

```sh
uv run bench.py run --out out/comparison --seed 42 \
  --target hachistep ../hachistep/tools/hachiware_adapter.py ../hachistep/target/release/hachistep \
  --target pocketwalker adapters/pocketwalker/adapter.py ../pocketwalker-build/pw-hachiware
```

Each `--target` supplies a display name, adapter, and optional executable. To run just
one emulator, supply its target only. Other emulators can implement the
[adapter contract](adapter.md).

`out/comparison/results.json` retains the report, raw samples, commands, host, seed,
and source and executable identities. To print the report again:

```sh
uv run bench.py report out/comparison/results.json
```

Choose a new output directory for every run. Keep the source checkouts and executables
unchanged during a comparison; the runner checks their identities and invalidates
scores if they change.

## Read the workload table

A cell such as `1200.0 | ok` means the emulator completed 1,200 seconds of device work
per second of host wall time, and every run passed its checks. A one-hour emulated
interval at that speed takes three host seconds.

| Result | Meaning |
| --- | --- |
| `ok` | Every run passed the workload's checks. |
| `FAILED` | The run completed and has a speed measurement, but its observed behavior failed a check. |
| `assisted` | Checks passed with the adapter performing some hardware work, such as converting optical pulses to bytes. The report names the assistance. |
| No speed | The run produced no usable timing. Inspect its status, logs, and raw samples for an execution error or a nonpositive timing difference. |

The report also gives host time per unit of work and the first failed check for each
workload. Head-to-head ratios show the first target's speed divided by the second's.
Measured comparisons include workloads both targets ran. Verified comparisons use
workloads both passed without adapter assistance.

Marks beside a speed describe the sample:

| Mark | Meaning |
| --- | --- |
| `*` | The host-time difference was less than half the requested `--min-seconds`. |
| `~` | Sample spread exceeded 25% of the median. |
| `w` | Process-tree CPU time was less than 90% of wall time. |

Raw wall and CPU samples remain in the JSON report.

## Choose workloads and measurement duration

```sh
uv run bench.py list
```

`--workload 'PATTERN'` selects workloads; `--case 'PATTERN'` selects diagnostics.
Repeat either option to combine selections. `--skip-conformance` runs workloads only;
`--skip-workloads` runs diagnostics only. `--samples` sets the sample count, with a
minimum of three. `--min-seconds` sets the desired duration of a timed difference.
`--cpu N` pins timed processes on hosts that support CPU affinity.

| Workload | Work |
| --- | --- |
| carry | Sensor acquisition, motion processing, EEPROM batches, and RTC interrupts in watch/subactive modes. |
| watch-face | Animated frames read from EEPROM, with LCD bank switching every 125 ms. |
| menu | Button input, redraws, and Timer W key clicks. |
| ir-sync | Repeated 136-byte write packets and read replies, checksums, EEPROM writes, and ACK/NAK handling. |
| ir-probe | Connection probes, polling, retries, and a timed peer response. |
| buzzer | Seeded melodies using Timer W PWM and compare interrupts while the CPU sleeps. |
| cpu | CRC, sort, multiply/divide, bit operations, copies, and recursion. |
| lcd-stream | Sustained NT7508 raster blits at varying SSU clocks. |
| eeprom-stream | M95512 page writes, status polling, and reads at varying SSU clocks. |
| ir-stream | SCI3 IrDA transmit bursts at varying rates with the receiver enabled. |

The six use workloads follow retail register sequences and loop shapes, including
waiting and sleeping. They repeat paced passes, with observations halfway through
a pass. The four hardware workloads keep a component busy. Guest digests and Timer W
durations check the result and elapsed hardware work, so skipping work affects the
checks too.

The infrared sync peer uses a fixed turnaround derived from documented transfer and
programming bounds. Receive data and reply checksums record packet contents;
transmit timing covers the first TDR3 write through TEND. `ir-stream` records transmit
timing in guest memory.

## How timing works

For each target, the runner selects short and long emulated intervals whose host-time
difference should take at least `--min-seconds`. Each sample runs both with the same
inputs and subtracts the short run's time from the long run's time. Dividing the added
device time by that host-time difference gives sustained speed with startup, loading,
export, and guest setup costs removed. Target and interval order alternate between
samples. The report uses the median difference, and every run is checked.

To measure startup and export costs as part of an actual firmware session, use
[session measurements](sessions.md#measure-complete-sessions).

## Summary figures

The day estimate combines the host time needed for assumed periods of use.
The floor is the slowest use workload. Busy-component workloads have a separate
summary:

| Figure | Calculation |
| --- | --- |
| Day speed | `D / sum(t_i / s_i)`, where `t_i` is device time assigned to a use workload, `s_i` is its speed, and `D` is the total assigned device time. |
| Floor | The slowest use workload, named in the report. |
| Hardware speed | The geometric mean of the four hardware workloads. |

The default day assigns 23 h 10 min to carry, 20 min to watch-face, 10 min each to menu
and ir-sync, 6 min to ir-probe, and 4 min to buzzer. These are assumed usage shares.
Mostly-carried, social-heavy, and equal-time profiles show how weighting changes the
result. Verified summaries require all included workloads to pass without assistance.
Measured summaries include all timed workloads and show their passing counts.

## Diagnostic scores

A hardware feature passes when all its diagnostic cases pass. The report groups
scores by component and separates documented expectations, reasoned expectations,
and cases requiring particular board conditions. It also identifies features used by
retail firmware. Unresolved expectations are excluded from scores.

See [diagnostics](diagnostics.md) to investigate a failed case and
[coverage controls](contributing.md#check-that-the-experiment-detects-wrong-behavior)
to audit the checks themselves.
