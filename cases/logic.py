"""Logic, shift, rotate, complement, extension and increment results with CCR.

REJ09B0213-0300 §2.2 gives each instruction's operation and its effect on
every CCR bit. The oracle below restates those definitions; byte and word
operations must also preserve the untouched lanes of ER0. Flags are read with
conditional branches (N, Z, V, C) so that a missing STC does not mask the
instruction under test; NEG records use STC because H is part of its result.
"""

from itertools import product

from diagnostic import Case
from .guest import image, record, record_flags

N, Z, V, C, H = 8, 4, 2, 1, 0x20
FILL = 0xA5C35A96
INCOMING = (0x00, 0x2B, 0xD4, 0x7F)
SUFFIX = {8: "b", 16: "w", 32: "l"}
REG = {8: "r0l", 16: "r0", 32: "er0"}
SRC = {8: "r1l", 16: "r1", 32: "er1"}


def values(bits):
    sign, limit = 1 << (bits - 1), 1 << bits
    return sorted({0, 1, 2, 0x0F, 0x10, sign - 1, sign, sign + 1, sign | 1 << (bits - 2),
                   limit - 2, limit - 1, 0x5A5A5A5A % limit, 0xC3C3C3C3 % limit})


def nz(result, bits, flags):
    flags &= ~(N | Z)
    flags |= N if result >> (bits - 1) & 1 else 0
    return flags | (Z if result == 0 else 0)


def unary(op, bits, a, ccr):
    """Return (result, CCR) for a one-operand instruction."""
    limit, sign = 1 << bits, 1 << (bits - 1)
    msb, lsb, carry = a >> (bits - 1) & 1, a & 1, ccr & C
    f = ccr
    if op == "not":
        r = ~a % limit
        return r, nz(r, bits, f) & ~V
    if op == "neg":
        r = -a % limit
        half = 1 << (bits - 4)
        f &= ~(H | V | C)
        f |= H if a % half else 0
        f |= V if a == sign else 0
        f |= C if a else 0
        return r, nz(r, bits, f)
    if op in ("extu", "exts"):
        half = bits // 2
        low = a % (1 << half)
        r = low | ((limit - (1 << half)) if op == "exts" and low >> (half - 1) & 1 else 0)
        return r, nz(r, bits, f) & ~V
    if op in ("shll", "shal"):
        r = a << 1 & (limit - 1)
        f = nz(r, bits, f) & ~(V | C) | msb
        if op == "shal" and msb != (a >> (bits - 2) & 1):
            f |= V
        return r, f
    if op == "shlr":
        r = a >> 1
        return r, nz(r, bits, f) & ~(V | C) | lsb
    if op == "shar":
        r = a >> 1 | msb << (bits - 1)
        return r, nz(r, bits, f) & ~(V | C) | lsb
    if op == "rotl":
        r = (a << 1 | msb) & (limit - 1)
        return r, nz(r, bits, f) & ~(V | C) | msb
    if op == "rotr":
        r = a >> 1 | lsb << (bits - 1)
        return r, nz(r, bits, f) & ~(V | C) | lsb
    if op == "rotxl":
        r = (a << 1 | carry) & (limit - 1)
        return r, nz(r, bits, f) & ~(V | C) | msb
    if op == "rotxr":
        r = a >> 1 | carry << (bits - 1)
        return r, nz(r, bits, f) & ~(V | C) | lsb
    step = int(op[-1])
    if op.startswith("inc"):
        r = (a + step) % limit
        overflow = sign - step <= a < sign
    else:
        r = (a - step) % limit
        overflow = sign <= a < sign + step
    return r, nz(r, bits, f) & ~V | (V if overflow else 0)


def binary(op, bits, a, b, ccr):
    r = {"and": a & b, "or": a | b, "xor": a ^ b}[op]
    return r, nz(r, bits, ccr) & ~V


def text(op, bits, immediate=False):
    reg, s = REG[bits], SUFFIX[bits]
    if op in ("and", "or", "xor"):
        return f"{op}.{s} {'#IMM' if immediate else SRC[bits]}, {reg}"
    if op[:3] in ("inc", "dec") and bits > 8:
        return f"{op[:3]}.{s} #{op[-1]}, {reg}"
    if op[:3] in ("inc", "dec"):
        return f"{op[:3]}.b {reg}"
    return f"{op}.{s} {reg}"


UNARY = {
    8: ("not", "neg", "shll", "shal", "shlr", "shar", "rotl", "rotr", "rotxl", "rotxr",
        "inc1", "dec1"),
    16: ("not", "neg", "extu", "exts", "shll", "shal", "shlr", "shar", "rotl", "rotr",
         "rotxl", "rotxr", "inc1", "inc2", "dec1", "dec2"),
}
UNARY[32] = UNARY[16]


def program(rows, whole_ccr=False):
    """rows: (asm text, initial ER0, ER1, incoming CCR, expected ER0, CCR).

    Records hold N, Z, V and C decoded by branches, or the whole CCR read with
    STC when ``whole_ccr`` (needed for the H flag).
    """
    body, observations = [], bytearray()
    for line, er0, er1, ccr, result, flags in rows:
        address = 0xF800 + len(observations)
        capture = record(address) if whole_ccr else record_flags(address)
        body.append(f"    mov.l #{er0:#x}, er0\n    mov.l #{er1:#x}, er1\n"
                    f"    ldc #{ccr:#x}, ccr\n    {line}\n" + capture)
        if not whole_ccr:
            flags &= 0x0F
        observations += result.to_bytes(4, "big") + bytes((flags, flags))
    body.append("    mov.b #0xa5, r0l\n    mov.b r0l, @0xff20")
    return image("\n".join(body)), {"ram": {"f800": observations.hex(), "ff20": "a5"}}


def lane(bits, value):
    keep = FILL & ~((1 << bits) - 1) if bits < 32 else 0
    return keep | value


def cases():
    evidence = {
        "kind": "documented",
        "source": "REJ09B0213-0300 §§2.2.4, 2.2.25, 2.2.29–31, 2.2.40, 2.2.42–43, "
                  "2.2.47–50, 2.2.53–56, 2.2.62 (operation and condition code of each "
                  "instruction): https://www.renesas.com/en/document/mah/h8300h-series-software-manual",
        "question": "Do logic, shift, rotate, complement, extension and increment instructions "
                    "give the defined result and CCR at boundary operands, preserving other lanes?",
        "limitation": "Boundary operands and four incoming CCR values, not an exhaustive enumeration.",
    }
    for bits in (8, 16, 32):
        for op in UNARY[bits]:
            rows = []
            for a, ccr in product(values(bits), INCOMING):
                r, f = unary(op, bits, a, ccr)
                rows.append((text(op, bits), lane(bits, a), 0, ccr, lane(bits, r), f))
            firmware, expected = program(rows, whole_ccr=op == "neg")
            yield Case(f"isa-logic-{op}-{bits}", firmware, expected,
                       evidence=evidence, milliseconds=20)
        for op, immediate in product(("and", "or", "xor"), (False, True)):
            rows = []
            pairs = list(product(values(bits), values(bits)))[::3]
            for (a, b), ccr in zip(pairs, INCOMING * len(pairs)):
                r, f = binary(op, bits, a, b, ccr)
                line = text(op, bits, immediate).replace("IMM", f"{b:#x}")
                rows.append((line, lane(bits, a), lane(bits, b) if bits < 32 else b, ccr,
                             lane(bits, r), f))
            firmware, expected = program(rows)
            yield Case(f"isa-logic-{op}{'-imm' if immediate else ''}-{bits}", firmware,
                       expected, evidence=evidence, milliseconds=20)
