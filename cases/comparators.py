"""Comparator arming, channel priority and reference selection."""

from diagnostic import Case
from .h8 import Program, handler


def cases():
    basis = {
        "kind": "documented",
        "source": "REJ09B0152-0300 Table3.1, §§18.3–18.5; internal/external-reference comparator "
        "application notes",
        "question": "Does CMDR read arm comparison and permit a settled difference to wake via the "
        "separate COMP0/COMP1 vectors 21/22?",
        "limitation": "Large voltage/time margins avoid relying on provisional analog response delay.",
    }
    p = Program()
    p.byte(0xFFFB, 6)
    p.byte(0xF0DC, 0xC8)
    p.code += bytes(128)  # settle before arming the comparator through CMDR
    p.code += bytes.fromhex("6a08f0de067f018040fc")
    image = handler(p.finish(), 21, "f8016a88f7806a08f0def8006a88f0de5670")
    timeline = "0,analog,pb4,1000\n200,analog,pb4,2100\n"
    yield Case(
        "comparator-read-armed-wake",
        image,
        {"ram": {"f780": "01"}, "interrupt_entries": 1},
        timeline,
        evidence=basis,
    )

    p = Program()
    for a, v in [(0xFFFB, 6), (0xF0DC, 0xC8), (0xF0DD, 0xC8)]:
        p.byte(a, v)
    p.code += bytes(128) + bytes.fromhex("6a08f0de067f018040fc")
    image = bytearray(p.finish())
    for channel, vector in enumerate([21, 22]):
        address = 0x200 + channel * 0x40
        image[vector * 2 : vector * 2 + 2] = address.to_bytes(2, "big")
        code = (
            bytes.fromhex("f8")
            + bytes([vector])
            + bytes.fromhex("6a88")
            + (0xF800 + channel).to_bytes(2, "big")
        )
        code += bytes.fromhex("6a08f8040a086a88f8046a88") + (0xF805 + channel).to_bytes(
            2, "big"
        )
        code += bytes.fromhex("6a08f0de6a88") + (0xF802 + channel).to_bytes(2, "big")
        code += (
            bytes.fromhex("f8")
            + bytes([0xEF if channel == 0 else 0xDF])
            + bytes.fromhex("6a88f0de5670")
        )
        image[address : address + len(code)] = code
    image[72:74] = bytes.fromhex("0280")  # reserved-vector sentinel
    image[0x280:0x28A] = bytes.fromhex("f8ee6a88f81040fe0000")
    timeline = "0,analog,pb4,1000\n0,analog,pb5,1000\n200,analog,pb4,2100\n200,analog,pb5,2100\n"
    yield Case(
        "comparator-channel-priority",
        bytes(image),
        {"ram": {"f800": "15163323020102", "f810": "00"}, "interrupt_entries": 2},
        timeline,
        evidence=basis,
    )

    p = Program()
    # Select external reference, retain prohibited CMLS and disabled CRS bits.
    for a, v in [(0xFFFB, 6), (0xFFC2, 1), (0xF0DC, 0xBF)]:
        p.byte(a, v)
    p.code += bytes(128) + bytes.fromhex("6a08f0dc6a88f8006a08f0de6a88f801")
    p.byte(0xFFFB, 4)
    p.code += bytes(128) + bytes.fromhex("6a08f0dc6a88f8026a08f0de6a88f803")
    p.byte(0xFFFB, 6)
    p.code += bytes(128) + bytes.fromhex("6a08f0dc6a88f8046a08f0de6a88f805")
    timeline = "0,analog,vcref,1500\n0,analog,pb4,1000\n"
    yield Case(
        "comparator-live-external-gating",
        p.finish(),
        {"ram": {"f800": "bf00bf00bf00"}},
        timeline,
        evidence={**basis, "kind": "software_reasoned"},
    )
