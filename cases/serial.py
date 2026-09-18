"""SCI framing and infrared signals through the board connections."""

from diagnostic import Case
from .h8 import Program


def cases():
    basis = {
        "kind": "documented",
        "source": "REJ09B0152-0300 §§8.2,14.3–14.8; TN-H8*-A333B/E corrected five-bit formats; lumirth/pw "
        "IrConfigure and IrStartSend for transceiver polarity",
        "question": "Do physical serial pins, corrected framing, status/data transfer, and transceiver "
        "shutdown obey their independent hardware contracts?",
        "limitation": "IR input pulses have generous timing margins; no analog receiver response or "
        "measured pulse phase is asserted.",
    }
    p = Program()
    for a, v in [
        (0xFFD6, 1),
        (0xFFE6, 5),
        (0xFFFA, 0x43),
        (0xFF91, 0xD0),
        (0xFF99, 1),
        (0xFFA7, 0x80),
        (0xFF9A, 0x20),
        (0xFF9B, 0xA5),
        (0xFFD6, 0),
    ]:
        p.byte(a, v)
    yield Case("infrared-transmit", p.finish(), {"ir_events": 10}, None, evidence=basis)
    p = Program()
    for a, v in [
        (0xFFD6, 1),
        (0xFFE6, 5),
        (0xFFFA, 0x43),
        (0xFF91, 0xD1),
        (0xFF99, 1),
        (0xFFA7, 0x80),
        (0xFF9A, 0x10),
        (0xFFD6, 0),
    ]:
        p.byte(a, v)
    p.code += bytes.fromhex("6a08ff9ce84047f86a08ff9d6a88f800")
    bits = [0] + [(0xA5 >> i) & 1 for i in range(8)] + [1]
    rows = ["# Nominal SIR pulses; digital software fixture, not a hardware capture."]
    for i, one in enumerate(bits):
        if not one:
            at = 500 + round(i * 64 * 1_000_000 / 3_686_400)
            rows.extend([f"{at},ir,1", f"{at + 3},ir,0"])
    yield Case(
        "infrared-receive",
        p.finish(),
        {"ram": {"f800": "a5"}},
        "\n".join(rows) + "\n",
        evidence=basis,
    )

    p = Program()
    p.byte(0xFFE6, 5)
    for value in [4, 5, 1, 0]:
        p.byte(0xFFD6, value)
    p.byte(0xFFFA, 0x43)
    p.byte(0xFF91, 0xD0)
    p.code += bytes.fromhex(
        "6a08ffd66a88f800"
    )  # PCR output reads latch, despite SCI's high TXD.
    p.byte(0xFF91, 0xD2)
    p.byte(0xFF91, 0xC0)
    yield Case(
        "sci-gpio-optical-mux",
        p.finish(),
        {"ram": {"f800": "02"}, "ir_events": 4},
        None,
        evidence=basis,
    )

    for name, smr, data, parity, stop, expected in [
        ("sci-five-n", 0x24, 0xF5, None, 1, "8415"),
        ("sci-five-even", 0x64, 0xF5, 1, 1, "8415"),
        ("sci-five-odd", 0x74, 0xF5, 0, 1, "8415"),
        ("sci-parity-error", 0x20, 0xA5, 1, 1, "8ca5"),
        ("sci-framing-error", 0, 0xA5, None, 0, "94a5"),
    ]:
        p = Program()
        for a, v in [(0xFFFA, 0x43), (0xFF98, smr), (0xFF99, 0), (0xFF9A, 0x10)]:
            p.byte(a, v)
        p.code += bytes.fromhex("6a08ff9ce87847f8")  # Wait for data OR a receive error.
        if name.startswith("sci-five"):
            p.code += bytes.fromhex("6a08ff9d6a88f8016a08ff9c6a88f800")
        else:
            p.code += bytes.fromhex("6a08ff9c6a88f8006a08ff9d6a88f801")
        bits = [0] + [(data >> i) & 1 for i in range(5 if smr & 4 else 8)]
        if parity is not None:
            bits.append(parity)
        bits.append(stop)
        rows = ["0,digital,p31,1"]
        for i, bit in enumerate(bits):
            rows.append(
                f"{500 + round(i * 32 * 1_000_000 / 3_686_400)},digital,p31,{bit}"
            )
        yield Case(
            name,
            p.finish(),
            {"ram": {"f800": expected}},
            "\n".join(rows) + "\n",
            evidence=basis,
        )

    p = Program()
    for a, v in [(0xFFFA, 0x43), (0xFF99, 0), (0xFF9A, 0x10)]:
        p.byte(a, v)
    p.code += bytes(5000)
    p.code += bytes.fromhex("6a08ff9c6a88f8006a08ff9d6a88f8016a08ff9c6a88f802")
    rows = ["0,digital,p31,1"]
    for start, value in [(500, 0xA5), (800, 0x3C)]:
        for i, bit in enumerate([0] + [(value >> i) & 1 for i in range(8)] + [1]):
            rows.append(
                f"{start + round(i * 32 * 1_000_000 / 3_686_400)},digital,p31,{bit}"
            )
    yield Case(
        "sci-overrun-retains-rdr",
        p.finish(),
        {"ram": {"f800": "e4a5a4"}},
        "\n".join(rows) + "\n",
        evidence=basis,
    )

    p = Program()
    for a, v in [
        (0xFFFA, 0x43),
        (0xFF91, 0xD0),
        (0xFF98, 0x80),
        (0xFF99, 0),
        (0xFF9A, 0x32),
        (0xFF9B, 0xA5),
    ]:
        p.byte(a, v)
    rows = ["0,digital,p30,1", "0,digital,p31,0"]
    for i in range(8):
        p.code += bytes.fromhex("6a08ffd6e80146f86a08ffd6")
        p.code += bytes((0x6A, 0x88, 0xF8, i))
        p.code += bytes.fromhex("6a08ffd6e80147f8")
        at = 500 + i * 100
        rows += [
            f"{at},digital,p31,{(0x3C >> i) & 1}",
            f"{at},digital,p30,0",
            f"{at + 50},digital,p30,1",
        ]
    p.code += bytes.fromhex("6a08ff9c6a88f8106a08ff9d6a88f811")
    yield Case(
        "sci-external-synchronous",
        p.finish(),
        {"ram": {"f800": "0400060202060004", "f810": "c43c"}},
        "\n".join(rows) + "\n",
        evidence=basis,
    )
