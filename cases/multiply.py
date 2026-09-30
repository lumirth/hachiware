"""Extended multiply results, aliases and instruction-specific CCR changes.

REJ09B0213-0300 §§2.2.38–39, pp.130–133 defines the operand slices, full
product width and flags. Compute products with Python integers. R0 and E0
byte destinations preserve their other word; word multiplication fills ER0.
"""

from itertools import product

from diagnostic import Case
from .h8 import Program


LAYOUTS = {
    8: ("r0-r1l", "r0-r0h", "r0-r0l", "e0-r1l", "e0-r0l"),
    16: ("er0-r1", "er0-e1", "er0-r0", "er0-e0"),
}


def operands(layout, a, b):
    """Return initial ER0/ER1 and documented source/destination selectors."""
    if layout == "r0-r1l":
        return 0xA5C35A00 | a, 0x12345600 | b, 9, 0
    if layout == "r0-r0h":
        return 0xA5C30000 | b << 8 | a, 0, 0, 0
    if layout == "r0-r0l":
        return 0xA5C35A00 | a, 0, 8, 0
    if layout == "e0-r1l":
        return (0x5A00 | a) << 16 | 0xC396, 0x12345600 | b, 9, 8
    if layout == "e0-r0l":
        return (0x5A00 | a) << 16 | 0xC300 | b, 0, 8, 8
    if layout == "er0-r1":
        return 0xA5C30000 | a, 0x5A960000 | b, 1, 0
    if layout == "er0-e1":
        return 0xA5C30000 | a, b << 16 | 0x5A96, 9, 0
    if layout == "er0-r0":
        return 0xA5C30000 | a, 0, 0, 0
    if layout == "er0-e0":
        return b << 16 | a, 0, 8, 0
    raise ValueError(layout)


def cases():
    evidence = {
        "kind": "documented",
        "source": "REJ09B0213-0300 §§2.2.38–39 pp.130–133; §1.4 register configuration: "
                  "https://www.renesas.com/en/document/mah/h8300h-series-software-manual",
        "question": "Do byte/word products use the documented operand slices, preserve untouched "
                    "register lanes, and change only the MULXS N/Z flags while MULXU preserves CCR?",
        "limitation": "Boundary operands include zero and both signs. This is not an exhaustive "
                      "operand enumeration and does not measure instruction timing.",
    }
    for bits, layouts in LAYOUTS.items():
        limit, sign = 1 << bits, 1 << (bits - 1)
        values = (0, 1, 2, sign - 1, sign, sign + 1, limit - 2, limit - 1)
        for signed, layout in product((False, True), layouts):
            p, observations = Program(), bytearray()
            # Record order is multiplicand, multiplier, incoming CCR.
            for a, b, incoming in product(values, values, (0, 0x0C, 0xF3, 0xFF)):
                # A source that is the destination's low slice must equal a.
                if layout in ("r0-r0l", "er0-r0") and b != a:
                    continue
                er0, er1, source, destination = operands(layout, a, b)
                p.code += bytes.fromhex("7a00") + er0.to_bytes(4, "big")
                p.code += bytes.fromhex("7a01") + er1.to_bytes(4, "big")
                p.code += bytes((7, incoming))
                if signed:
                    p.code += bytes.fromhex("01c0")
                p.code += bytes((0x50 if bits == 8 else 0x52, source << 4 | destination))
                p.record_er0_ccr(0xF800 + len(observations))
                left, right = a, b
                if signed:
                    left, right = (v if v < sign else v - limit for v in (a, b))
                result = left * right
                flags = incoming
                if signed:
                    flags = (incoming & ~0x0C) | (8 if result < 0 else 4 if result == 0 else 0)
                result %= limit * limit
                if bits == 8:
                    if destination == 8:
                        result = result << 16 | (er0 & 0xFFFF)
                    else:
                        result |= er0 & 0xFFFF0000
                observations += result.to_bytes(4, "big") + bytes((flags, flags))
            p.byte(0xFF20, 0xA5)
            yield Case(
                f"multiply-{'signed' if signed else 'unsigned'}-{bits}-{layout}", p.finish(),
                {"ram": {"f800": observations.hex(), "ff20": "a5"}},
                evidence=evidence, milliseconds=20,
            )
