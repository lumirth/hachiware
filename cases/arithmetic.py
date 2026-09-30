"""Arithmetic at carry, half-carry and signed-range boundaries.

The integer oracle uses unbounded arithmetic and signed representability. Programs
capture all of ER0 and CCR before reporting changes the flags. This also checks
that byte and word results preserve their other register lanes.
"""

from itertools import product

from diagnostic import Case
from .h8 import Program


OPERATIONS = (
    ("add", 8, "0898"), ("sub", 8, "1898"), ("cmp", 8, "1c98"),
    ("addx", 8, "0e98"), ("subx", 8, "1e98"),
    ("add", 16, "0910"), ("sub", 16, "1910"), ("cmp", 16, "1d10"),
    ("add", 32, "0a90"), ("sub", 32, "1a90"), ("cmp", 32, "1f90"),
)


def boundaries(bits):
    half, sign, limit = 1 << (bits - 4), 1 << (bits - 1), 1 << bits
    return sorted({0, 1, 2, half - 1, half, half + 1,
                   sign - 2, sign - 1, sign, sign + 1, limit - 2, limit - 1})


def expected(operation, bits, a, b, incoming):
    limit, sign, half = 1 << bits, 1 << (bits - 1), 1 << (bits - 4)
    carry = (incoming & 1) if operation.endswith("x") else 0
    subtract = operation in ("sub", "subx", "cmp")
    signed_a, signed_b = (v if v < sign else v - limit for v in (a, b))
    raw = a - b - carry if subtract else a + b + carry
    signed = signed_a - signed_b - carry if subtract else signed_a + signed_b + carry
    result = raw % limit
    half_raw = a % half - b % half - carry if subtract else a % half + b % half + carry
    flags = incoming & 0xD0
    flags |= 0x20 if not 0 <= half_raw < half else 0
    flags |= 8 if result >= sign else 0
    flags |= 4 if result == 0 and (not operation.endswith("x") or incoming & 4) else 0
    flags |= 2 if not -sign <= signed < sign else 0
    flags |= 1 if not 0 <= raw < limit else 0
    destination = a if operation == "cmp" else result
    return (0xA5C35A96 & ~(limit - 1)) | destination, flags


def cases():
    basis = {
        "kind": "documented",
        "source": "REJ09B0213-0300 §§2.2.1, 2.2.3, 2.2.22, 2.2.59, 2.2.61 and Table 2.9; "
                  "https://www.renesas.com/en/document/mah/h8300h-series-software-manual; "
                  "REJ09B0152-0300 §2.2.3 and Appendix A.1 note (3). "
                  "https://www.renesas.com/en/document/mah/h838602r-group-hardware-manual",
        "question": "Do results, preserved register lanes and CCR bits agree at unsigned, "
                    "half-carry and signed-range boundaries, including incoming carry and sticky Z?",
        "limitation": "Boundary pairs cover all widths but do not enumerate every 16-bit or 32-bit operand. "
                      "Target Appendix A.1 resolves the conflicting fresh-Z SUBX prose in the software manual.",
    }
    for operation, bits, opcode in OPERATIONS:
        rows = list(product(boundaries(bits), boundaries(bits), (0, 5, 0xDA, 0xFF)))
        # Row order is destination, source, incoming CCR. Each row has six bytes.
        # Three hundred records fit below the program's stack.
        for start in range(0, len(rows), 300):
            p, observations = Program(), bytearray()
            for a, b, incoming in rows[start:start + 300]:
                initial = (0xA5C35A96 & ~((1 << bits) - 1)) | a
                p.code += bytes.fromhex("7a00") + initial.to_bytes(4, "big")
                p.code += bytes.fromhex("7a01") + b.to_bytes(4, "big")
                p.code += bytes((7, incoming)) + bytes.fromhex(opcode)
                address = 0xF800 + len(observations)
                p.record_er0_ccr(address)
                result, flags = expected(operation, bits, a, b, incoming)
                observations += result.to_bytes(4, "big") + bytes((flags, flags))
            p.byte(0xFF20, 0xA5)
            yield Case(
                f"arithmetic-{operation}-{bits}-{start // 300}", p.finish(),
                {"ram": {"f800": observations.hex(), "ff20": "a5"}}, None,
                evidence=basis, milliseconds=20,
            )
