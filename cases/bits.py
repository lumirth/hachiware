"""Bit manipulation on registers and memory, with CCR effects.

REJ09B0213-0300 §§2.2.6, 2.2.8–17, 2.2.19–21 define BSET, BCLR, BNOT, BTST,
BLD/BILD, BST/BIST and the C-flag logic BAND/BIAND, BOR/BIOR, BXOR/BIXOR.
The bit number comes from an immediate or the lower three bits of a general
register; operands are a register, @ERd or @aa:8.
"""

from itertools import product

from diagnostic import Case
from .guest import image, record_flags

FILL = 0xA5C35A00
VALUES = (0x00, 0xFF, 0x5A, 0xA5)
INCOMING = (0x00, 0x01, 0xFE, 0xFF)
TARGETS = {"reg": "r0l", "ind": "@er1", "abs": "@0xff40:8"}


def expected(op, bit, value, ccr):
    """Return (operand after, CCR after)."""
    b, c = value >> bit & 1, ccr & 1
    if op == "bset":
        return value | 1 << bit, ccr
    if op == "bclr":
        return value & ~(1 << bit), ccr
    if op == "bnot":
        return value ^ 1 << bit, ccr
    if op == "btst":
        return value, ccr & ~4 | (0 if b else 4)
    if op in ("bst", "bist"):
        c ^= op == "bist"
        return value & ~(1 << bit) | c << bit, ccr
    inverted = op in ("bild", "biand", "bior", "bixor")
    b ^= inverted
    base = op[2:] if inverted else op[1:]
    c = {"ld": b, "and": c & b, "or": c | b, "xor": c ^ b}[base]
    return value, ccr & ~1 | c


IMMEDIATE_ONLY = ("bld", "bild", "bst", "bist", "band", "biand", "bor", "bior", "bxor", "bixor")
REGISTER_NUMBER = ("bset", "bclr", "bnot", "btst")


def cases():
    evidence = {
        "kind": "documented",
        "source": "REJ09B0213-0300 §§2.2.6, 2.2.8–2.2.17, 2.2.19–2.2.21 (operation, addressing "
                  "modes and condition codes): "
                  "https://www.renesas.com/en/document/mah/h8300h-series-software-manual",
        "question": "Do bit instructions change exactly the selected bit or C/Z flag for each "
                    "operand form, using only the low three bits of a register bit number?",
        "limitation": "Four operand patterns and four incoming CCR values per bit position.",
    }
    for op in REGISTER_NUMBER + IMMEDIATE_ONLY:
        sources = ("imm", "regn") if op in REGISTER_NUMBER else ("imm",)
        for source, target in product(sources, TARGETS):
            body, observations = [], bytearray()
            rows = list(product(range(8), VALUES, INCOMING))[::2]
            for bit, value, ccr in rows:
                address = 0xF800 + len(observations)
                number = f"#{bit}" if source == "imm" else "r2h"
                lines = [f"    mov.l #{FILL | value:#x}, er0",
                         "    mov.l #0xfe00, er1",
                         f"    mov.b #{0xF8 | bit:#x}, r2h" if source == "regn" else "",
                         f"    mov.b #{value:#x}, r3l",
                         "    mov.b r3l, @0xfe00", "    mov.b r3l, @0xff40",
                         f"    ldc #{ccr:#x}, ccr",
                         f"    {op} {number}, {TARGETS[target]}"]
                memory = {"reg": None, "ind": "@0xfe00", "abs": "@0xff40"}[target]
                lines.append(record_flags(address, memory))
                body.append("\n".join(x for x in lines if x))
                result, flags = expected(op, bit, value, ccr)
                flags &= 0x0F  # N, Z, V and C, read with conditional branches
                observations += (FILL | result).to_bytes(4, "big") + bytes((flags, flags))
            body.append("    mov.b #0xa5, r0l\n    mov.b r0l, @0xff20")
            name = f"isa-bit-{op}-{target}" + ("-regnum" if source == "regn" else "")
            yield Case(name, image("\n".join(body)),
                       {"ram": {"f800": observations.hex(), "ff20": "a5"}},
                       evidence=evidence, milliseconds=20)
