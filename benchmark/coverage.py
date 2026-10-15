"""Hardware coverage map and conformance scoring.

Each feature names the hardware block it belongs to, whether the retail
firmware uses it (from lumirth/pw), and the conformance cases (shell patterns)
and workloads that exercise it. A case belongs to the first feature whose
patterns match it, and every case must belong to one.

A feature is conformant on a target only if every one of its cases passes.
Partial credit inside a feature does not exist, so passing the easy cases of
many features earns nothing, and the number of cases a family happens to
generate does not change its weight. Cases are graded by evidence:

- documented: expectations from manufacturer documentation or measurement.
  The headline counts features conformant on their documented cases.
- inferred: expectations reasoned from documentation where it is silent.
  Reported with the documented cases as a second figure.
- conditional: expectations that hold only for named board quantities (the
  case's ``conditions``). They apply to targets that declare the same values
  and are reported separately, never in the headline.
"""

from __future__ import annotations

from fnmatch import fnmatchcase

# (block, feature, firmware-used, case patterns, workloads)
# Instruction forms counted as firmware-used are those of compiled retail code;
# register bit numbers, inverted bit logic, rotates through carry and similar
# forms appear only in the beyond-firmware features.
CPU = ("cpu",)
ALL = ("carry", "watch-face", "menu", "ir-sync", "ir-probe", "buzzer", "cpu", "lcd-stream",
       "eeprom-stream", "ir-stream")
SCREEN = ("watch-face", "menu", "lcd-stream")
MOTION = ("carry",)
TICK = ("carry", "watch-face", "menu", "buzzer")

FIRMWARE_LOGIC = tuple(f"isa-logic-{op}-{bits}" for op, bits in (
    ("not", 8), ("neg", 8), ("neg", 16), ("extu", 16), ("extu", 32), ("exts", 16), ("exts", 32),
    ("shll", 8), ("shll", 16), ("shll", 32), ("shlr", 8), ("shlr", 16), ("shlr", 32),
    ("shar", 16), ("shar", 32), ("rotl", 8), ("rotl", 16), ("inc1", 8), ("inc1", 16),
    ("inc2", 16), ("inc1", 32), ("dec1", 8), ("dec1", 16), ("and", 8), ("and-imm", 8),
    ("or", 8), ("or-imm", 8), ("xor", 8), ("xor-imm", 8), ("and", 16), ("and-imm", 16),
    ("or", 16), ("or-imm", 16), ("xor", 16), ("xor", 32), ("and-imm", 32)))
FIRMWARE_BITS = tuple(f"isa-bit-{name}" for name in (
    "bset-reg", "bset-ind", "bset-abs", "bset-reg-regnum", "bclr-reg", "bclr-ind", "bclr-abs",
    "bnot-ind", "btst-reg", "bld-reg", "bld-ind", "bld-abs", "bst-reg", "bst-ind"))

# (block, feature, firmware-used, case patterns, workloads)
FEATURES = (
    # CPU instruction set and timing
    ("cpu", "half-carry flag H as STC reads it", False, ("arithmetic-h-*",), ()),
    ("cpu", "add/sub/cmp/addx/subx flags (8/16/32-bit)", True,
     ("arithmetic-*", "add-byte-flags"), CPU),
    ("cpu", "logic, shift, not/neg/ext and increment forms of compiled code", True,
     FIRMWARE_LOGIC, CPU),
    ("cpu", "other logic, shift and rotate forms (SHAL, ROTR, ROTXL/ROTXR, wide NOT/NEG)",
     False, ("isa-logic-*",), ()),
    ("cpu", "bit manipulation forms of compiled code", True, FIRMWARE_BITS, CPU),
    ("cpu", "other bit forms (register bit numbers, BAND/BOR/BXOR, inverted forms)", False,
     ("isa-bit-*",), ()),
    ("cpu", "MOV addressing modes and widths, register aliases", True,
     ("register-aliases", "long-displacement-store", "predecrement-alias-*"), CPU),
    ("cpu", "multiply MULXU/MULXS", True, ("multiply-*",), CPU),
    ("cpu", "divide DIVXU/DIVXS incl. overflow and zero", True,
     ("divide-*", "division-flags-and-continuation"), CPU),
    ("cpu", "decimal adjust DAA/DAS", False, ("decimal-*",), ()),
    ("cpu", "branches, BSR/JSR/RTS, conditions", True,
     ("branch-*", "call-return-stack"), CPU),
    ("cpu", "EEPMOV block move", False, ("isa-eepmov-*",), ()),
    ("cpu", "LDC/STC/ANDC/ORC/XORC on CCR", True, ("isa-ccr-*",), TICK),
    ("cpu", "TRAPA", False, ("isa-trapa*",), ()),
    ("cpu", "prefetch and self-modifying code", False,
     ("prefetch-before-self-modifying-store", "call-prefetch-before-stack-write",
      "execute-from-ram", "code-rewrite-*"), ()),
    ("cpu_timing", "peripheral register access states", True, ("timing-access",),
     ("watch-face",)),
    ("cpu_timing", "instruction state counts (Table A.4)", True, ("timing-*",),
     ("carry", "cpu")),
    # Exceptions and interrupts
    ("interrupts", "vector priority among simultaneous requests", True,
     ("interrupt-priority-*",), ()),
    ("interrupts", "interrupt entry, CCR/PC stacking, RTE", True,
     ("exception-ccr-stack-word", "interrupt-*"), TICK),
    ("interrupts", "IRQ0/IRQ1 edge detection and enable gating", True, ("irq-*",), ()),
    ("interrupts", "NMI", False, ("nmi-*",), ()),
    # Clocks and power
    ("power", "sleep and watch modes, peripheral clocks per mode (Tables 5.2, 5.3)", True,
     ("power-sleep-*", "power-watch-*"), TICK),
    ("power", "direct transitions and the direct-transition interrupt", True,
     ("direct-clock-*",), MOTION),
    ("power", "subactive mode at phiW", True, ("power-speed-subactive-1",), MOTION),
    ("power", "medium-speed and divided subactive clocks", False, ("power-speed-*",), ()),
    ("power", "oscillator selection", False, ("oscillator-*",), ()),
    ("power", "module standby (CKSTPR1/2)", True, ("power-module-standby-*",), ALL),
    ("supply", "supply collapse, RAM retention, reset circuit", True,
     ("power-*-retention*", "power-retention-*"), ()),
    # Memory
    ("bus", "register map holes, widths and mixed accesses", True,
     ("register-native-word-byte-lanes", "register-holes-and-mixed-word"), ()),
    ("flash", "flash programming, erase, protection", False, ("flash-*",), ()),
    # Timers
    ("timer_b1", "interval/auto-reload, prescaler selection, interrupt", True,
     ("timer-b1-*",), TICK),
    ("timer_w", "compare match, clear, overflow, PWM, input capture, interrupts", True,
     ("timer-w-*",), SCREEN + CPU + ("ir-sync", "ir-probe", "buzzer")),
    ("interrupts", "interrupts taken while polling peripheral status", True,
     ("poll-interrupt-*",), ()),
    ("rtc", "calendar counting, busy period, periodic interrupts, flags", True, ("rtc-*",),
     MOTION),
    ("watchdog", "write qualification, overflow reset, interval mode", True, ("watchdog-*",),
     ALL),
    ("aec", "asynchronous event counter", False, ("aec-*",), ()),
    # Analog
    ("comparators", "comparator wake and gating", False,
     ("comparator-*", "register-comparator-*"), ()),
    ("adc", "battery measurement, triggers, clocks", True, ("adc-*",), ()),
    # Serial
    ("sci3", "asynchronous formats, errors, IrDA, synchronous mode", True,
     ("sci-*", "infrared-*"), ("ir-sync", "ir-probe", "ir-stream")),
    ("ssu", "master transfers, overrun, modes, slave operation", True, ("ssu-*",),
     TICK + ("lcd-stream", "eeprom-stream")),
    ("iic", "IIC2 master/slave", False, ("iic-*",), ()),
    # Board devices
    ("ports", "button levels on port B", True, ("port-*",), ("menu",)),
    ("lcd", "NT7508 RAM layout, commands, palette, scrolling", True, ("lcd-*",), SCREEN),
    ("eeprom", "M95512 commands, page writes, status, power", True,
     ("eeprom-*", "serial-eeprom-*"), ("carry", "ir-sync", "eeprom-stream") + SCREEN),
    ("accelerometer", "BMA150 conversion, range, offsets, SPI/I2C", True, ("sensor-*",),
     MOTION + ("watch-face",)),
)


def classify(case: dict) -> str:
    """Evidence grade of a manifest case: documented, inferred, conditional or unresolved."""
    kind = case["expectation"]["kind"]
    if kind == "unresolved":
        return "unresolved"
    if case.get("conditions"):
        return "conditional"
    return "documented" if kind in ("documented", "hardware_measured") else "inferred"


def case_features(case_names) -> dict[str, tuple[str, str, bool]]:
    """(block, feature, firmware-used) of the first feature matching each case."""
    out = {}
    for name in case_names:
        for block, feature, used, patterns, _ in FEATURES:
            if any(fnmatchcase(name, p) for p in patterns):
                out[name] = (block, feature, used)
                break
        else:
            raise ValueError(f"case {name} is not in the coverage map")
    return out


def conformance_score(results: dict, cases: dict) -> dict:
    """Feature conformance by evidence grade; see the module notes."""
    owner = case_features(results)
    features: dict = {}
    for name, result in results.items():
        block, feature, used = owner[name]
        entry = features.setdefault((block, feature), {
            "block": block, "feature": feature, "firmware_used": used, "cases": {}})
        entry["cases"][name] = (classify(cases[name]), result["status"])

    def grade(grades: set[str]) -> dict:
        total = conformant = 0
        split = {True: [0, 0], False: [0, 0]}
        blocks: dict = {}
        failing = []
        for entry in features.values():
            relevant = {n: s for n, (g, s) in entry["cases"].items() if g in grades}
            if not relevant:
                continue
            ok = all(s == "pass" for s in relevant.values())
            total += 1
            conformant += ok
            split[entry["firmware_used"]][0] += ok
            split[entry["firmware_used"]][1] += 1
            b = blocks.setdefault(entry["block"], [0, 0])
            b[0] += ok
            b[1] += 1
            if not ok:
                failing.append({
                    "block": entry["block"], "feature": entry["feature"],
                    "failed": sorted(n for n, s in relevant.items() if s != "pass"),
                    "cases": len(relevant)})
        return {"conformant": conformant, "features": total,
                "firmware_used": {"conformant": split[True][0], "features": split[True][1]},
                "beyond_firmware": {"conformant": split[False][0], "features": split[False][1]},
                "blocks": {k: {"conformant": v[0], "features": v[1]}
                           for k, v in sorted(blocks.items())},
                "failing": failing}

    counts: dict = {}
    for entry in features.values():
        for g, status in entry["cases"].values():
            c = counts.setdefault(g, {"pass": 0, "total": 0, "not_applicable": 0})
            c["total"] += 1
            c["pass"] += status == "pass"
            c["not_applicable"] += status == "not_applicable"
    return {
        "documented": grade({"documented"}),
        "with_inferred": grade({"documented", "inferred"}),
        "conditional": grade({"conditional"}),
        "cases": counts,
    }


def print_map(workload_names=()) -> None:
    from cases import cases

    names = [c.name for c in cases()]
    owner = case_features(names)
    known = set(workload_names)
    print("\nCoverage map (F = used by retail firmware)")
    for block, feature, used, _patterns, loads in FEATURES:
        found = [n for n, (_b, f, _u) in owner.items() if f == feature]
        status = f"{len(found)} cases" if found else "no cases"
        if loads:
            unknown = [w for w in loads if known and w not in known]
            if unknown:
                raise ValueError(f"coverage map names unknown workloads {unknown}")
            status += f", workloads: {', '.join(loads)}"
        if not found and not loads:
            status = "UNCOVERED"
        print(f"  {'F' if used else ' '} {block:<14} {feature}: {status}")
