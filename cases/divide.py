"""Defined extended-division results and preserved register/CCR fields.

REJ09B0213-0300 §§2.2.26–27, pp.83–95 specifies quotient/remainder lanes.
These cases exclude zero divisors and quotient overflow. The CPU family cases
separately check flags and continued execution when result bits are unspecified.
The DIVXU.W prose says "upper 8 bits" on p.92; its 16-bit remainder diagram
and the complete division example on p.96 establish the full E register lane.
"""

from itertools import product

from diagnostic import Case
from .h8 import Program


def pairs(bits, signed):
    limit, sign = 1 << bits, 1 << (bits - 1)
    if signed:
        return (
            (0, 1), (0, -1), (1, 2), (-1, 2), (1, -2), (-1, -2),
            (sign - 1, 1), (-sign, 1), (2 * sign - 1, 2),
            (1 - 2 * sign, 2), ((sign - 1) ** 2, sign - 1),
            (sign * (sign - 1), -sign),
        )
    return (
        (0, 1), (0, sign), (1, 2), (sign - 1, sign), (sign, sign),
        (limit - 1, sign), (limit - 1, limit - 1), (limit, sign),
        (limit + 1, sign), ((limit - 1) ** 2, limit - 1),
        ((limit - 1) ** 2 + limit - 2, limit - 1), (limit - 1, 1),
    )


def cases():
    evidence = {
        "kind": "documented",
        "source": "REJ09B0213-0300 §§2.2.26–27 pp.83–95, including DIVXS N notes "
                  "on pp.84/86, signed remainder rules on p.90, and word remainder "
                  "diagram/example on pp.92/96: "
                  "https://www.renesas.com/en/document/mah/h8300h-series-software-manual",
        "question": "Do representable byte/word divisions put quotient and remainder in the "
                    "documented lanes, preserve untouched lanes and CCR bits, and set N "
                    "from operand signs even for a signed quotient truncated to zero?",
        "limitation": "No result-bit expectation for zero divisors or quotient overflow. "
                      "These programs do not measure instruction timing.",
    }
    for bits, signed, upper in product((8, 16), (False, True), (False, True)):
        p, observations = Program(), bytearray()
        limit, sign = 1 << bits, 1 << (bits - 1)
        # Record order is dividend/divisor pair, then incoming CCR.
        for (dividend, divisor), incoming in product(pairs(bits, signed), (0, 0x0C, 0xF3, 0xFF)):
            raw = dividend % (limit * limit)
            encoded_divisor = divisor % limit
            if bits == 8:
                er0 = raw << 16 | 0x5A96 if upper else 0xA5C30000 | raw
                er1 = 0x12345600 | encoded_divisor
                source, destination = 9, 8 if upper else 0
            else:
                er0 = raw
                er1 = encoded_divisor << 16 | 0x5A96 if upper else 0xA5C30000 | encoded_divisor
                source, destination = 9 if upper else 1, 0
            p.code += bytes.fromhex("7a00") + er0.to_bytes(4, "big")
            p.code += bytes.fromhex("7a01") + er1.to_bytes(4, "big")
            p.code += bytes((7, incoming))
            if signed:
                p.code += bytes.fromhex("01d0")
            p.code += bytes((0x51 if bits == 8 else 0x53, source << 4 | destination))
            p.record_er0_ccr(0xF800 + len(observations))
            # Integer magnitudes avoid Python's negative floor-division rule.
            quotient = abs(dividend) // abs(divisor)
            negative = (dividend < 0) != (divisor < 0) if signed else divisor >= sign
            if signed and negative:
                quotient = -quotient
            remainder = dividend - quotient * divisor
            assert (-sign <= quotient < sign) if signed else (0 <= quotient < limit)
            result = (remainder % limit) << bits | (quotient % limit)
            if bits == 8:
                if upper:
                    result = result << 16 | (er0 & 0xFFFF)
                else:
                    result |= er0 & 0xFFFF0000
            flags = (incoming & ~0x0C) | (8 if negative else 0)
            observations += result.to_bytes(4, "big") + bytes((flags, flags))
        p.byte(0xFF20, 0xA5)
        layout = ("e0" if upper else "r0") if bits == 8 else ("e1" if upper else "r1")
        yield Case(
            f"divide-{'signed' if signed else 'unsigned'}-{bits}-{layout}", p.finish(),
            {"ram": {"f800": observations.hex(), "ff20": "a5"}},
            evidence=evidence, milliseconds=20,
        )
