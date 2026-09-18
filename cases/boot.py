"""Serial bootstrap inputs and RAM guests for Renesas Table 6.2."""

from diagnostic import Case


def uart(rows, start, value):
    # 2400 baud; each new assignment changes a physical RXD input level.
    for bit in range(10):
        high = bit == 9 or (bit != 0 and bool(value & (1 << (bit - 1))))
        rows.append(f"{start + bit * 1250 // 3},digital,p31,{int(high)}")


def timeline(length, payload, begin):
    rows = ["0,reset,0", "0,nmi,0", "0,digital,p30,0", "100,reset,1"]
    uart(rows, 1000, 0)
    uart(rows, 20000, 0x55)
    for index, value in enumerate(length.to_bytes(2, "big") + payload):
        uart(rows, begin + index * 6000, value)
    return "\n".join(rows) + "\n"


def cases():
    basis = {
        "kind": "documented",
        "source": "REJ09B0152-0300 §6.3/Table6.2 and §6.4; TN-H8*-A414A/E target geometry",
        "question": "Does physical 2400-baud boot erase all six blocks when nonblank, accept an odd RAM "
        "payload and retain BRR/SCI/GPIO handoff state?",
        "physical_device": "Boot mode erases all nonblank flash; use only on an authorized sacrificial "
        "device.",
        "limitation": "Checks erase results and documented handoff state. Invalid lengths echo and wait "
        "for reset under the inferred loader control flow.",
    }
    # The uploaded code initializes its own stack and records state guaranteed
    # at handoff. Both H8 instructions and expectations are literal.
    code = bytearray.fromhex("7a070000ff70")
    for index, address in enumerate([0xFF99, 0xFF9A, 0xFFD6, 0xFFE6]):
        code += bytes.fromhex("6a08") + address.to_bytes(2, "big")
        if address == 0xFFD6:
            code += bytes.fromhex("e804")
        code += bytes.fromhex("6a88") + (0xF800 + index).to_bytes(2, "big")
    addresses = [
        0,
        0x3FF,
        0x400,
        0x7FF,
        0x800,
        0xBFF,
        0xC00,
        0xFFF,
        0x1000,
        0x7FFF,
        0x8000,
        0xBFFF,
    ]
    for index, address in enumerate(addresses):
        code += bytes.fromhex("6a08") + address.to_bytes(2, "big")
        code += bytes.fromhex("6a88") + (0xF804 + index).to_bytes(2, "big")
    code += bytes.fromhex("f8a56a88f820018040fc")
    # Odd payload length is legal; this final data byte is not executed.
    code += b"\x5a"
    assert len(code) % 2 == 1
    for name, fill, begin in [("blank", 255, 50000), ("erase", 0, 1100000)]:
        yield Case(
            f"boot-{name}-upload",
            bytes([fill]) * 49152,
            {
                "ram": {
                    "f800": "2f000404" + "ff" * 12,
                    "f820": "a5",
                    f"{0xFB80 + len(code) - 1:04x}": "5a",
                },
                "sleeping": True,
            },
            timeline(len(code), code, begin),
            evidence=basis,
            milliseconds=2200,
        )
    for length in [0, 1025]:
        yield Case(
            f"boot-invalid-length-{length}",
            bytes([255]) * 49152,
            {"ram": {"fb80": "0000", "ff7f": "00"}, "er0": 0, "sleeping": False},
            timeline(length, b"\x7a", 50000),
            evidence={**basis, "kind": "software_reasoned"},
            milliseconds=2200,
        )
