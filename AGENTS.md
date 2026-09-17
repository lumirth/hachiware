# Agent guidance

Keep this suite independent of emulator implementations. Use manufacturer
documentation, actual observations, firmware evidence, and reasoned inference
for expectations. Never obtain expected values from the emulator under test.

Write cases in hardware terms. Prefer small guest programs and literal expected
results; generate combinations when that is clearer. Keep emulator adapters in
their own projects. Do not consult past HachiStep implementations.

Run `python3 -m unittest discover -s tests` after changing the builder or runner.
Run affected diagnostics through the available adapter after changing cases.
Record sources with the case, and never call software results hardware captures.
