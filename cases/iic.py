"""IIC2 register, address, interrupt and STOP sequencing."""

from diagnostic import Case
from .h8 import Program, handler


def cases():
    basis = {
        "kind": "documented",
        "source": "REJ09B0152-0300 §16.3–16.5; TN-MC*-A022A/E and A023A/E",
        "question": "Do byte-wide registers, shared-vector interrupt, physical address frames, "
        "read-qualified flags and STOP sequencing follow the IIC2 contract?",
        "limitation": "Clocked input gives ample filter/setup margin; no inferred subcycle race is "
        "asserted.",
    }
    p = Program()
    for i, a in enumerate(range(0xF078, 0xF080)):
        p.code += bytes((0x6A, 8, a >> 8, a & 255, 0x6A, 0x88, 0xF8, i))
    yield Case(
        "iic-reset-map",
        p.finish(),
        {"ram": {"f800": "007d38000000ffff"}},
        None,
        evidence=basis,
    )

    p = Program()
    p.byte(0xF07A, 0x88)
    p.byte(0xF07E, 1)
    p.code += bytes.fromhex("6a08f07e6a88f800")
    p.byte(0xF078, 0x90)
    p.byte(0xF07C, 0)
    p.code += bytes.fromhex("6a08f07c6a88f801")
    p.byte(0xF07C, 0)
    p.code += bytes.fromhex("6a08f07c6a88f802")
    yield Case(
        "iic-holding-order-and-flag-clear",
        p.finish(),
        {"ram": {"f800": "808000"}},
        None,
        evidence=basis,
    )

    p = Program()
    for a, v in [
        (0xFFFB, 0x24),
        (0xF087, 3),
        (0xF078, 0xB0),
        (0xF079, 0xBD),
        (0xF07E, 0xA0),
    ]:
        p.byte(a, v)
    p.code += bytes.fromhex("6a08f07ce84047f86a08f07c6a88f8006a08f07b6a88f801")
    p.byte(0xF079, 0x3D)
    p.code += bytes.fromhex(
        "6a08f07ce80847f86a08f07c6a88f8046a08f0786a88f8026a08f0796a88f803"
    )
    yield Case(
        "iic-master-nack-and-stop",
        p.finish(),
        {"ram": {"f800": "c002b07dc8"}},
        None,
        evidence=basis,
    )

    def iic_address_input(address):
        edges = [(0, "p90", 1), (0, "p91", 1), (100, "p91", 0)]
        time = 120
        for bit in range(7, -1, -1):
            edges += [
                (time, "p90", 0),
                (time, "p91", int(bool(address & (1 << bit)))),
                (time + 20, "p90", 1),
            ]
            time += 40
        edges += [
            (time, "p90", 0),
            (time, "p91", 1),
            (time + 20, "p90", 1),
            (time + 40, "p90", 0),
            (time + 60, "p91", 0),
            (time + 80, "p90", 1),
            (time + 100, "p91", 1),
        ]
        return "".join(f"{t},digital,{pin},{v}\n" for t, pin, v in edges)

    for address, expected in [(0x54, "5402807d0a"), (0, "0003807d0b")]:
        p = Program()
        for a, v in [(0xFFFB, 0x24), (0xF087, 3), (0xF07D, 0x54), (0xF078, 0x80)]:
            p.byte(a, v)
        p.code += bytes.fromhex("6a08f07ce82047f86a08f07f6a88f8006a08f07c6a88f801")
        p.code += bytes.fromhex(
            "6a08f07ce80847f86a08f07c6a88f8046a08f0786a88f8026a08f0796a88f803"
        )
        yield Case(
            "iic-slave-" + ("address" if address else "general-call"),
            p.finish(),
            {"ram": {"f800": expected}},
            iic_address_input(address),
            evidence=basis,
        )

    p = Program()
    for a, v in [
        (0xFFFB, 0x24),
        (0xF087, 3),
        (0xF07D, 0x54),
        (0xF07B, 0x20),
        (0xF078, 0x80),
    ]:
        p.byte(a, v)
    p.code += bytes.fromhex("067f018040fc")
    image = handler(p.finish(), 34, "6a08f07f6a88f8006a08f07c6a88f8015670")
    yield Case(
        "iic-slave-receive-interrupt",
        image,
        {"ram": {"f800": "5402"}, "interrupt_entries": 1},
        iic_address_input(0x54),
        evidence=basis,
    )
