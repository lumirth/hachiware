# Agent guidance

Keep this suite independent of emulator implementations. Use manufacturer
documentation, actual observations, firmware evidence, and reasoned inference
for expectations. Never obtain expected values from the emulator under test.

Write cases in hardware terms. Prefer small guest programs and literal expected
results; generate combinations when that is clearer. Keep emulator adapters in
their own projects; `adapters/pocketwalker/` exists only because PocketWalker has
none. Do not consult past HachiStep implementations.

Do not add unit, integration, tautological or change-detector tests. Test by
running cases and workloads end to end through an adapter. After changing a case
or workload, run it through an available adapter and run `bench.py audit` on it;
every check must fail its controls. A benchmark change must not favor an emulator
or an implementation technique: workloads take their data from the seed, observe
only memory every adapter exports, and report every speed beside its check
result; only fully verified groups get a verified figure.
Keep sources, conditions and expectations beside the case they explain.
Separate documented behavior from reasoned inference in each case's evidence metadata.

Write concise documentation and comments that explain behavior, constraints or
reasoning. Keep progress and individual run reports in the task, commits or issues.
When adding documentation, update the existing owner, consolidate overlap and remove
superseded material after preserving useful reasoning. Split topics when it improves
navigation. Use plain words and active voice; cut filler and rhetorical contrasts.
Preserve precise hardware terms and notation. Use `writing-for-agents` for agent
instructions, not general documentation.
