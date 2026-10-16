# Add a hardware experiment

Start with an observable consequence. The M95512 wraps writes within a 128-byte
page, so writing `AA BB CC DD` at `0x007e` should leave `AA BB` there and `CC DD`
at `0x0000`. Linear addressing and skipped writes produce different bytes.
The [`serial-eeprom-page-wrap` case](../cases/eeprom.py) runs that experiment
through the guest's serial interface, with the datasheet as its source.

Keep a new case's program, expected observations, source evidence, physical inputs,
and required conditions together. Existing cases provide the format;
`build.py --list` shows what readers will see. Use `documented` for explicit source
behavior and `software_reasoned` for an inference. See the
[evidence reference](diagnostics.md#read-the-evidence) for the full grading scheme.
Generated images and reports go under ignored `out/`.

## Check that the experiment detects wrong behavior

Run the case through an available adapter using the
[diagnostic workflow](diagnostics.md#run-the-selected-diagnostics), then audit it:

```sh
uv run bench.py audit --out out/audit --case serial-eeprom-page-wrap --skip-workloads \
  --target hachistep ../hachistep/tools/hachiware_adapter.py ../hachistep/target/release/hachistep
```

The diagnostic control replaces the guest with an idle loop. It must complete and
export observations, then fail the expected-result check. A passing control means
the check missed the omitted work. A fault or missing export means the control
itself didn't run correctly. Either is an audit finding.

For workloads, select `--workload 'NAME*' --skip-conformance`. Their controls use
another seed's firmware, EEPROM, and inputs. `bench.py run --audit` includes controls
in a comparison. Findings withhold aggregate scores and return status 1.

## Workloads and sessions

A workload must leave observable results for the work it times. Use seeded data and
guest memory that every adapter can export. Run changed workloads and their controls;
the [benchmark guide](benchmark.md) explains the measurement and reporting rules.

For a [firmware session](sessions.md), choose input timelines and capture points
that preserve work still in progress. `--scenarios FILE` selects the definitions.
Saved-result checks need firmware evidence for their addresses and expected values.

Keep emulator adapters in their own projects and individual validation reports in
the change's PR or issue. The [adapter contract](adapter.md) defines the connection.
