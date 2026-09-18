"""BMA150 acquisition, configuration and serial transfers."""

from diagnostic import Case
from .h8 import Program, handler


REGISTER_EVIDENCE = {
    "kind": "documented",
    "source": "Bosch BMA150 Rev1.6 register map, §§3.2,3.5,4.1; Bosch bma150_calc_new_offset and "
    "set_range",
    "question": "Do serial transfers, qualification/status, defaults, temperature, and offset/range "
    "produce their specified observations?",
}


def cases():
    basis = REGISTER_EVIDENCE
    for name, enable, expected, timeline in [
        ("sensor-low-g", 1, "0a00", "0,accel,0,0,0\n"),
        ("sensor-high-g", 2, "0500", None),
        ("sensor-self-test-input", 1, "0a00", None),
    ]:
        p = Program()
        for a, v in [
            (0xFFFB, 0x14),
            (0xF0E0, 0x8C),
            (0xF0E1, 0x40),
            (0xF0E2, 0x86),
            (0xF0E3, 0xC0),
            (0xFFE4, 7),
            (0xFFD4, 5),
            (0xF087, 8),
            (0xFFEC, 1),
            (0xFFDC, 1),
        ]:
            p.byte(a, v)
        for a, v in [(0x0B, enable), (0x0C, 32), (0x0D, 0), (0x0E, 32), (0x0F, 0)]:
            p.byte(0xFFDC, 0)
            p.send(a)
            p.send(v)
            p.byte(0xFFDC, 1)
        if name == "sensor-self-test-input":
            p.byte(0xFFDC, 0)
            p.send(0x0A)
            p.send(8)
            p.byte(0xFFDC, 1)
        p.code += bytes(20000)
        for slot in range(2):
            p.byte(0xFFDC, 0)
            p.send(0x89)
            p.send(0)
            p.code += bytes((0x6A, 0x88, 0xF8, slot))
            p.byte(0xFFDC, 1)
            p.byte(0xFFDC, 0)
            p.send(0x0A)
            p.send(0x40)
            p.byte(0xFFDC, 1)
        yield Case(
            name, p.finish(), {"ram": {"f800": expected}}, timeline, evidence=basis
        )
    for name in [
        "sensor-self-test-completion",
        "sensor-image-update",
        "sensor-autowake-asleep",
        "sensor-autowake-awake",
    ]:
        p = Program()
        for a, v in [
            (0xFFFB, 0x14),
            (0xF0E0, 0x8C),
            (0xF0E1, 0x40),
            (0xF0E2, 0x86),
            (0xF0E3, 0xC0),
            (0xFFE4, 7),
            (0xFFD4, 5),
            (0xF087, 8),
            (0xFFEC, 1),
            (0xFFDC, 1),
        ]:
            p.byte(a, v)
        timeline = None
        milliseconds = 8
        if name.startswith("sensor-autowake"):
            milliseconds = 23
            for a, v in [(0x0B, 0), (0x15, 0x81), (0x0A, 1)]:
                p.byte(0xFFDC, 0)
                p.send(a)
                p.send(v)
                p.byte(0xFFDC, 1)
            irq = Program()
            irq.byte(0xFFDC, 0)
            irq.send(0x80)
            irq.send(0)
            irq.code += bytes.fromhex("6a88f800")
            irq.byte(0xFFDC, 1)
            image = handler(p.finish(), 7, (irq.code[4:] + bytes.fromhex("40fe")).hex())
            awake = name.endswith("-awake")
            timeline = f"{21000 if awake else 1000},nmi,0\n"
            expected = "02" if awake else "ff"
        elif name == "sensor-self-test-completion":
            p.byte(0xFFDC, 0)
            p.send(0x0A)
            p.send(4)
            p.byte(0xFFDC, 1)
            p.code += bytes(20000)
            p.byte(0xFFDC, 0)
            p.send(0x89)
            for slot in range(2):
                p.send(0)
                p.code += bytes((0x6A, 0x88, 0xF8, slot))
            p.byte(0xFFDC, 1)
            image = p.finish()
            expected = "8000"
        else:
            p.byte(0xFFDC, 0)
            p.send(0x0A)
            p.send(0x30)
            p.byte(0xFFDC, 1)
            p.byte(0xFFDC, 0)
            p.send(0x8B)
            p.send(0)
            p.code += bytes.fromhex("6a88f800")
            p.byte(0xFFDC, 1)
            p.byte(0xFFDC, 0)
            p.send(0x0B)
            p.send(0)
            p.byte(0xFFDC, 1)
            p.code += bytes(2000)
            p.byte(0xFFDC, 0)
            p.send(0x8B)
            p.send(0)
            p.code += bytes.fromhex("6a88f801")
            p.byte(0xFFDC, 1)
            image = p.finish()
            expected = "ff03"
        yield Case(
            name,
            image,
            {"ram": {"f800": expected}},
            timeline,
            evidence=basis,
            milliseconds=milliseconds,
        )
    p = Program()
    for a, v in [
        (0xFFFB, 0x14),
        (0xF0E0, 0x8C),
        (0xF0E1, 0x40),
        (0xF0E2, 0x86),
        (0xF0E3, 0xC0),
        (0xFFE4, 7),
        (0xFFD4, 5),
        (0xF087, 8),
        (0xFFEC, 1),
        (0xFFDC, 1),
    ]:
        p.byte(a, v)
    p.code += bytes(12000)  # First complete cold vector, still +1 g.
    p.byte(0xFFDC, 0)
    p.send(0x86)
    p.send(0)
    p.code += bytes.fromhex("6a88f800")
    p.byte(0xFFDC, 1)
    p.byte(0xFFDC, 0)
    p.send(0x0A)
    p.send(0x20)
    p.byte(0xFFDC, 1)
    p.code += bytes(14000)  # Image reload and analog settling at -1 g.
    for slot, address in [(1, 7), (2, 6), (3, 7)]:
        p.byte(0xFFDC, 0)
        p.send(0x80 | address)
        p.send(0)
        if slot == 2:
            p.code += bytes.fromhex("e8c0")  # Freshness can change between these reads.
        p.code += bytes((0x6A, 0x88, 0xF8, slot))
        p.byte(0xFFDC, 1)
    yield Case(
        "sensor-image-keeps-read-pair",
        p.finish(),
        {"ram": {"f800": "012000e0"}},
        "4000,accel,0,0,-1000000\n",
        evidence=basis,
    )

    basis = {
        "kind": "software_reasoned",
        "source": "Bosch BMA150 Rev1.6 sections 3.1.3 and 8.1: second-order 1500-Hz analog stage before a "
        "3-kHz ADC scan",
        "question": "Does a 50-us acceleration pulse between nominal X conversion apertures leave an "
        "observable decaying response, while zero input stays zero?",
        "limitation": "Uses the configured startup and scan phase. Checks that a pulse leaves a decaying response.",
    }
    conditions = {"sensor_startup_us": 3000, "sensor_scan_order": "temperature,x,y,z"}
    for pulse in [False, True]:
        p = Program()
        for a, v in [
            (0xFFFB, 0x14),
            (0xF0E0, 0x8C),
            (0xF0E1, 0x40),
            (0xF0E2, 0x86),
            (0xF0E3, 0xC0),
            (0xFFE4, 7),
            (0xFFD4, 5),
            (0xF087, 8),
            (0xFFEC, 1),
            (0xFFDC, 1),
        ]:
            p.byte(a, v)
        p.byte(0xFFDC, 0)
        p.send(0x14)
        p.send(6)
        p.byte(0xFFDC, 1)  # +/-2 g, 1500 Hz.
        p.byte(0xFFDC, 0)
        p.send(0x15)
        p.send(0x88)
        p.byte(0xFFDC, 1)  # Unshadowed MSB reads.
        p.byte(0xF800, 0)
        p.code += bytes.fromhex("79020200")  # Poll through the pulse's decay.
        loop = len(p.code)
        p.byte(0xFFDC, 0)
        p.send(0x83)
        p.send(0)  # X MSB only; no freshness bit.
        p.code += bytes.fromhex("e8ff4706")  # Any nonzero sample latches the witness.
        p.byte(0xF800, 1)
        p.byte(0xFFDC, 1)
        p.code += bytes.fromhex("1b52")  # DEC.W #1,R2; BNE loop.
        p.code += bytes((0x46, (loop - len(p.code) - 2) & 255))
        timeline = (
            "3200,accel,1000000,0,1000000\n3250,accel,0,0,1000000\n" if pulse else None
        )
        yield Case(
            "sensor-between-conversion-" + ("pulse" if pulse else "control"),
            p.finish(),
            {"ram": {"f800": "01" if pulse else "00"}},
            timeline,
            evidence=basis,
            conditions=conditions,
        )

    basis = REGISTER_EVIDENCE
    for name, reg14, offset, expected, timeline in [
        (
            "sensor-factory-defaults",
            None,
            None,
            {"f800": "031496a0960000a20d0e80"},
            None,
        ),
        ("sensor-offset-2g", 6, 0x40, {"f800": "014264"}, None),
        ("sensor-offset-4g", 14, 0x40, {"f800": "012164"}, None),
        ("sensor-offset-8g", 22, 0x40, {"f800": "811064"}, None),
        ("sensor-temperature", 6, None, {"f800": "014082"}, "0,temperature,35000\n"),
    ]:
        p = Program()
        for a, v in [
            (0xFFFB, 0x14),
            (0xF0E0, 0x8C),
            (0xF0E1, 0x40),
            (0xF0E2, 0x86),
            (0xF0E3, 0xC0),
            (0xFFE4, 7),
            (0xFFD4, 5),
            (0xF087, 8),
            (0xFFEC, 1),
            (0xFFDC, 1),
        ]:
            p.byte(a, v)
        for address, value in ([(0x14, reg14)] if reg14 is not None else []) + (
            [(0x0A, 0x10), (0x18, offset)] if offset is not None else []
        ):
            p.byte(0xFFDC, 0)
            p.send(address)
            p.send(value)
            p.byte(0xFFDC, 1)
        p.code += bytes(20000)  # More than 3 ms cold acquisition time.
        p.byte(0xFFDC, 0)
        p.send(0x8B if reg14 is None else 0x86)
        for byte in range(11 if reg14 is None else 3):
            p.send(0)
            p.code += bytes((0x6A, 0x88, 0xF8, byte))
        p.byte(0xFFDC, 1)
        yield Case(name, p.finish(), {"ram": expected}, timeline, evidence=basis)
    p = Program()
    for a, v in [
        (0xFFFB, 0x14),
        (0xF0E0, 0x8C),
        (0xF0E1, 0x40),
        (0xF0E2, 0x86),
        (0xF0E3, 0xC0),
        (0xFFE4, 7),
        (0xFFD4, 5),
        (0xF087, 8),
        (0xFFEC, 1),
        (0xFFDC, 1),
    ]:
        p.byte(a, v)
    p.byte(0xFFDC, 0)
    for value in [0x0C, 0x20, 0x0D, 2]:
        p.send(value)
    p.byte(0xFFDC, 1)
    p.byte(0xFFDC, 0)
    p.send(0x8C)
    for address in [0xF800, 0xF801]:
        p.send(0)
        p.code += bytes((0x6A, 0x88, address >> 8, address & 255))
    p.byte(0xFFDC, 1)
    yield Case(
        "sensor-paired-writes",
        p.finish(),
        {"ram": {"f800": "2002"}},
        None,
        evidence=basis,
    )

    p = Program()
    p.byte(0xFFE4, 7)
    p.byte(0xFFD4, 5)  # LCD/EEPROM deselected.
    p.byte(0xFFDC, 3)
    p.byte(0xFFEC, 7)  # GPIO CS/SCK/SDI, mode-3 idle.

    def gpio_byte(value):
        for bit in range(7, -1, -1):
            data = ((value >> bit) & 1) << 2
            p.byte(0xFFDC, data)
            p.byte(0xFFDC, data | 2)

    p.byte(0xFFDC, 2)
    gpio_byte(0x15)
    gpio_byte(0)  # Select three-wire, same write protocol.
    p.byte(0xFFDC, 3)
    p.byte(0xFFDC, 2)
    gpio_byte(0x80)
    p.byte(0xFFEC, 3)  # Release SDI/SDA before turnaround.
    p.byte(0xFFDC, 0)
    p.byte(0xFFDC, 2)  # Ninth edge launches D7.
    for bit in range(16):
        p.byte(0xFFDC, 0)
        p.code += bytes((0x6A, 0x08, 0xFF, 0xDC, 0x6A, 0x88, 0xF8, bit))
        p.byte(0xFFDC, 2)
    p.byte(0xFFDC, 3)
    yield Case(
        "sensor-three-wire-gpio",
        p.finish(),
        {"ram": {"f800": "00000000000004000000000400000000"}},
        None,
        evidence=basis,
    )
