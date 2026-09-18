# Agent guidance

Keep this suite independent of emulator implementations. Use manufacturer
documentation, actual observations, firmware evidence, and reasoned inference
for expectations. Never obtain expected values from the emulator under test.

Write cases in hardware terms. Prefer small guest programs and literal expected
results; generate combinations when that is clearer. Keep emulator adapters in
their own projects. Do not consult past HachiStep implementations.

Run `uv run -m unittest discover -s tests` after changing the builder or runner.
Run affected diagnostics through the available adapter after changing cases.
Keep sources, conditions and expectations beside the case they explain.

Write concise documentation and comments that explain behavior, constraints or
reasoning. Keep progress and individual run reports in the task, commits or issues.
When adding documentation, update the existing owner, consolidate overlap and remove
superseded material after preserving useful reasoning. Split topics when it improves
navigation. Use plain words and active voice; cut filler and rhetorical contrasts.
