# Benchmarking emulators

Build each target, then use the same run to compare them:

```sh
uv run bench.py run --out out/bench-1 --seed 42 \
  --target hachistep ../hachistep/tools/hachiware_adapter.py ../hachistep/target/release/hachistep \
  --target pocketwalker adapters/pocketwalker/adapter.py ../pocketwalker-build/pw-hachiware
uv run bench.py report out/bench-1/results.json
```

`bench.py list` describes the workloads. `--workload PATTERN` and `--case PATTERN`
select subsets. `--skip-conformance` measures workloads only; `--skip-workloads` runs
diagnostics only. Use `--samples` with at least three samples and `--min-seconds` to
choose measurement duration. `--cpu N` pins timed processes on hosts supporting affinity.

Outputs require a new directory. The JSON report keeps raw samples, input seed, host,
source and binary identities, and every check result. Source or executable changes
during a run invalidate its scores and return exit status 1.

## PocketWalker setup

Clone an unmodified [PocketWalker](https://github.com/h4lfheart/pocketwalker) checkout.
With CMake 3.20 or newer and a C++23 compiler:

```sh
cmake -S adapters/pocketwalker -B ../pocketwalker-build \
  -DPW_ROOT=/absolute/path/to/pocketwalker -DCMAKE_BUILD_TYPE=Release
cmake --build ../pocketwalker-build
```

The bridge builds the upstream core with its desktop release settings. Its adapter
declares any input assistance in the report.

## Workloads

Guests use seeded data, physical inputs, and memory observations. Hardware timers
measure their work against instruction state counts and device transfer times.

| Workload | Tier | Work |
| --- | --- | --- |
| carry | Use | Sensor acquisition, motion processing, EEPROM batches, and RTC interrupts in watch/subactive modes. |
| watch-face | Use | Animated frames read from EEPROM, with LCD bank switching every 125 ms. |
| menu | Use | Button input, redraws, and Timer W key clicks. |
| ir-sync | Use | Repeated 136-byte write packets and read replies, checksums, EEPROM writes, and ACK/NAK handling. |
| ir-probe | Use | Connection probes, polling, retries, and a timed response when a peer answers. |
| buzzer | Use | Seeded melodies using Timer W PWM and compare interrupts while the CPU sleeps. |
| cpu | Hardware | CRC, sort, multiply/divide, bit operations, copies, and recursion. |
| lcd-stream | Hardware | Sustained NT7508 raster blits at varying SSU clocks. |
| eeprom-stream | Hardware | M95512 page writes, status polling, and reads at varying SSU clocks. |
| ir-stream | Hardware | SCI3 IrDA transmit bursts at varying rates with the receiver enabled. |

Use workloads follow retail register sequences and loop shapes. They repeat paced
passes and are observed halfway through a pass. Hardware workloads run continuously,
recording a ring of work-item digests and Timer W durations. The checks verify both
results and elapsed hardware work.

The infrared sync peer sends packets after a fixed turnaround derived from documented
transfer and programming bounds. Receive data and reply checksums witness packet
contents; transmit witnesses measure from the first TDR3 write through TEND.
`ir-stream` checks transmit timing through memory witnesses.

## Speed figures

Speed is emulated seconds per host second, shown as times realtime. Reports include
wall and process-tree CPU time. A fault, timeout, or incomplete horizon is an error.
Completed runs retain their timing even when correctness checks fail.

The per-workload table shows `ok`, `FAILED`, or `assisted` beside every speed. Assistance
means the adapter performed part of the hardware work. Verified figures require every
included workload to pass without assistance. Measured figures include every timed
workload and show how many passed. Pairwise tables retain both kinds of comparison.

Aggregate figures are:

- Day speed: `D / sum(t_i / s_i)`, the speed of an assumed day profile.
- Floor: the slowest use workload, named in the report.
- Hardware speed: the geometric mean of the four hardware workloads.

The default day assigns 23 h 10 min to carry, 20 min to watch-face, 10 min each to menu
and ir-sync, 6 min to ir-probe, and 4 min to buzzer. These are assumed usage shares.
The report also gives mostly-carried, social-heavy, and equal-time variants.

Marks indicate measurement conditions: `*` means the longest horizon was too short;
`~` means sample spread exceeded 25% of the median; `w` means process-tree CPU time was
less than 90% of wall time. Use raw samples and CPU figures to interpret noisy rows.

## Timing method

For each target, the runner chooses two horizons whose difference should take at least
`--min-seconds`. Each sample runs both with the same input file and subtracts the short
run's time from the long run's time. This removes startup, loading, export, and guest
setup costs. Speed divides the emulated interval by the median time difference.
Target and horizon order alternate between samples. Every run is checked.

## Conformance and controls

A feature passes only when all its cases pass. Counts are split by hardware block,
retail use, and evidence grade. Documented expectations form the headline score;
inferred expectations form another figure. Cases requiring particular board conditions
appear separately. Unresolved expectations are excluded.

Run controls after changing coverage:

```sh
uv run bench.py audit --out out/audit-1 \
  --target hachistep ../hachistep/tools/hachiware_adapter.py ../hachistep/target/release/hachistep
```

The audit replaces each guest with an idle loop and each workload with another seed's
image, EEPROM, and inputs. Each control must complete and export observations, then fail
its check. Passing controls, faults, missing observations, and runner errors are findings.
Findings withhold aggregate scores and return exit status 1. `run --audit` includes the
same controls in a benchmark run.

Case metadata records numerical assumptions, including initial RAM and reset conditions.
Paced checks observe selected points in a pass. Physical captures can extend coverage
where those observations leave behavior unresolved.
