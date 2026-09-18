"""H8 register lanes, arithmetic and instruction access ordering."""

from diagnostic import Case
from .h8 import Program


def cases():
    basis = {
        "kind": "documented",
        "source": "H8/300H software manual REJ09B0213-0300, CPU register configuration and MOV "
        "instructions",
        "question": "Do byte, word and long writes preserve the overlapping register lanes?",
    }
    p = Program()
    p.code += bytes.fromhex("7a0011223344f0aaf8bb7908ccdd01006b80f800")
    yield Case(
        "register-aliases",
        p.finish(),
        {"ram": {"f800": "ccddaabb"}},
        None,
        evidence=basis,
    )

    basis = {
        "kind": "documented",
        "source": "REJ09B0213-0300 §2.2.35 p.127; GNU gas h8300/movlh.s and h8300.exp (8ea833b70679)",
        "question": "Does the assembler-emitted MOV.L displacement store execute with its high selector "
        "bit?",
    }
    p = Program()
    # GNU gas movlh.s / h8300.exp golden bytes, also MOV.L manual p.127.
    p.code += bytes.fromhex("7a010000f8007a0011223344010078906ba000000020")
    p.code += bytes.fromhex("02096a89f800")
    yield Case(
        "long-displacement-store",
        p.finish(),
        {"ram": {"f800": "80", "f820": "11223344"}},
        None,
        evidence=basis,
    )

    basis = {
        "kind": "documented",
        "source": "H8/300H software manual REJ09B0213-0300, ADD.B and STC instructions",
        "question": "Does 0x80 + 0x80 produce zero with H=0, N=0, Z=1, V=1 and C=1?",
    }
    p = Program()
    p.code += bytes.fromhex("f880888002096a88f8006a89f801")
    yield Case(
        "add-byte-flags", p.finish(), {"ram": {"f800": "0087"}}, None, evidence=basis
    )

    basis = {
        "kind": "documented",
        "source": "H8/300H software manual REJ09B0213-0300, JSR and RTS instructions",
        "question": "Does a subroutine return to the stacked address and preserve its result?",
    }
    p = Program()
    p.code += bytes.fromhex("f82a5e0001206a88f80040fe")
    p.code += bytes(0x20 - len(p.code))
    p.code += bytes.fromhex("88015470")
    yield Case(
        "call-return-stack",
        p.finish(),
        {"ram": {"f800": "2b", "ff7e": "010a"}},
        None,
        evidence=basis,
    )

    basis = {
        "kind": "documented",
        "source": "H8/300H software manual REJ09B0213-0300, MOV.L and JMP instructions; H8/38606 memory "
        "map",
        "question": "Can instructions written into ordinary RAM execute and alter a register?",
    }
    p = Program()
    p.code += bytes.fromhex("7a00f8a540fe01006b80f8205a00f820")
    yield Case(
        "execute-from-ram", p.finish(), {"er0": 0xF8A540A5}, None, evidence=basis
    )

    basis = {
        "kind": "documented",
        "source": "ADE-602-053A MOV.B/W/L usage notes pp.121/123/125",
        "question": "Does predecrement precede sampling an aliased source field?",
    }
    # MOV stores must sample an aliased register *after* predecrement.
    # ADE-602-053A pp.121,123,125. Literal expectations are not obtained
    # by executing HachiStep or importing its decoder.
    for suffix, opcode, address, expected in [
        ("byte", "6ca2", "f7ff", "f7"),
        ("word", "6da2", "f7fe", "f7fe"),
        ("long", "01006da2", "f7fc", "1122f7fc"),
    ]:
        p = Program()
        p.code += bytes.fromhex("7a021122f800" + opcode)
        yield Case(
            "predecrement-alias-" + suffix,
            p.finish(),
            {"ram": {address: expected}},
            None,
            evidence=basis,
        )

    basis = {
        "kind": "documented",
        "source": "REJ09B0213-0300 §2.8 Table 2.10 pp.239–241",
        "question": "Does a real prefetched opcode survive a later write to its RAM address?",
    }
    # A store's NEXT fetch precedes its data write. The overwritten first word
    # must execute from the pipeline; the following extension remains live.
    p = Program()
    body = bytes.fromhex("7900f82a6b80f828f8116a88f80040fe")
    for offset in range(0, len(body), 2):
        p.word(0xF820 + offset, int.from_bytes(body[offset : offset + 2], "big"))
    p.code += bytes.fromhex("5a00f820")
    yield Case(
        "prefetch-before-self-modifying-store",
        p.finish(),
        {"ram": {"f800": "11", "f828": "f82a"}},
        None,
        evidence=basis,
    )

    # JSR @aa:24 fetches the target before pushing the return PC. Here the
    # stack aliases that target, making the bus order visible in plain RAM.
    p = Program()
    body = bytes.fromhex("f8116a88f80040fe")
    for offset in range(0, len(body), 2):
        p.word(0xF822 + offset, int.from_bytes(body[offset : offset + 2], "big"))
    p.code += bytes.fromhex("7907f8245e00f822")
    yield Case(
        "call-prefetch-before-stack-write",
        p.finish(),
        {"ram": {"f800": "11"}},
        None,
        evidence=basis,
    )

    basis = {
        "kind": "documented",
        "source": "REJ09B0213-0300 §§2.2.26–2.2.27 pp.83–95",
        "question": "Do all division widths continue with documented operand-sign and zero-divisor flags?",
        "limitation": "Undefined zero-divisor/overflow destination bits are deliberately not asserted.",
    }
    # The manual defines these flags and continued execution even when the
    # quotient/remainder bits are unspecified. Do not certify those bits.
    p = Program()
    divisions = [
        (False, False, 0x1234, 0, 0xF7),
        (False, True, 0x12345678, 0, 0xF7),
        (True, False, 0xFFFF, 0, 0xFF),
        (True, True, 0xFFFFFFFF, 0, 0xFF),
        (False, False, 0xFFFF, 1, 0xF3),
        (False, True, 0xFFFFFFFF, 1, 0xF3),
        (True, False, 0x8000, 0xFF, 0xF3),
        (True, True, 0x80000000, 0xFFFF, 0xF3),
        (True, False, 0xFFFF, 2, 0xFB),
        (True, True, 0xFFFFFFFF, 2, 0xFB),
        (False, True, 0x10000, 0x8000, 0xFB),
    ]
    for index, (signed, word, dividend, divisor, flags) in enumerate(divisions):
        p.code += bytes.fromhex("7a01") + dividend.to_bytes(4, "big")
        p.code += (
            bytes.fromhex("7900") + divisor.to_bytes(2, "big") + bytes.fromhex("07f3")
        )
        if signed:
            p.code += bytes.fromhex("01d0")
        p.code += bytes.fromhex("5301" if word else "5181")
        p.code += bytes.fromhex("020a6a8a") + (0xF800 + index).to_bytes(2, "big")
    p.byte(0xF820, 0xA5)
    yield Case(
        "division-flags-and-continuation",
        p.finish(),
        {"ram": {"f800": bytes(row[4] for row in divisions).hex(), "f820": "a5"}},
        None,
        evidence=basis,
    )
