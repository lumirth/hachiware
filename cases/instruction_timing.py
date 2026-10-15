"""Instruction execution states measured differentially with Timer W at phi.

Each record times 40 and then 8 copies of one instruction sequence with the
same start/stop code and stores the difference, so counter start and stop
latency cancel and the record equals 32 times the sequence's states. The
states come from REJ09B0152-0300 Appendix A.3/Table A.4 with the access states
of section 20.1 (``spec/register_access.tsv``), as computed by ``timing.py``.
"""

from diagnostic import Case
from . import timing
from .asm import Listing, assemble

SCRATCH = 0xFB00
LONG, SHORT = 40, 8

GROUPS = {
    "move": (
        "mov.b r0l, r1h", "mov.w r1, r2", "mov.l er2, er3", "mov.b #0x5a, r0l",
        "mov.w #0x1234, r1", "mov.l #0x12345678, er3", "mov.b @er6, r0l",
        "mov.w @(0x10,er6), r1", "mov.l @(0x20,er6), er2", "mov.b r0l, @(0x31,er6)",
        "mov.w r1, @(0x12,er6)", "mov.l er2, @(0x24,er6)", "mov.w @0xfb40, r3",
        "mov.b r3l, @0xfb41", "mov.l @0xfb44, er1", "mov.l er1, @0xfb48",
        "mov.b @0xff40:8, r0h", "mov.b r0h, @0xff41:8", "mov.w @0x0200, r1",
        "mov.l @(0x10,er6), er1\n    mov.l er1, @(0x10,er6)",
        "mov.b @er6+, r0l\n    mov.b r0l, @-er6", "mov.w @er6+, r1\n    mov.w r1, @-er6",
        "mov.l @er6+, er1\n    mov.l er1, @-er6", "push.w r1\n    pop.w r1",
        "push.l er2\n    pop.l er2",
    ),
    "alu": (
        "add.b r0l, r1h", "add.w r1, r2", "add.l er2, er3", "add.b #0x11, r0h",
        "add.w #0x1234, r3", "add.l #0x12345, er2", "sub.w r3, r1", "sub.l er1, er2",
        "cmp.b r0l, r1l", "cmp.w #0x55, r2", "cmp.l er2, er3", "cmp.l #0x10000, er3",
        "addx r0l, r1h", "subx #1, r2l", "and.b #0x3c, r1l", "or.w r2, r3",
        "xor.l er1, er3", "and.l #0xffff0000, er2", "not.b r0h", "neg.w r1", "not.l er2",
        "inc.b r2l", "dec.w #1, r3", "inc.l #2, er1", "adds #4, er2", "subs #1, er3",
        "daa r0l", "das r1l", "exts.w r2", "extu.l er1",
    ),
    "shift": (
        "shll.b r0l", "shar.w r1", "rotxl.l er2", "rotr.b r3h", "shlr.l er3",
        "shal.w r2", "rotl.l er1", "rotxr.b r0h",
    ),
    "muldiv": (
        "mulxu.b r0l, r1", "mulxu.w r1, er2", "mulxs.b r0l, r1", "mulxs.w r3, er2",
        "mov.b #3, r0l\n    divxu.b r0l, r1", "mov.w #7, r3\n    divxu.w r3, er2",
        "mov.b #3, r0l\n    divxs.b r0l, r1", "mov.w #7, r3\n    divxs.w r3, er2",
    ),
    "bit": (
        "bset #3, r0l", "bclr #1, r1h", "bnot #2, r2l", "btst #4, r3l", "bld #0, r0h",
        "bst #5, r1l", "bxor #6, r2h", "biand #7, r0l", "bset r0l, r1h",
        "bset #1, @er6", "bclr #2, @er6", "bnot #3, @0xff40:8", "btst #4, @er6",
        "bld #5, @0xff40:8", "bst #6, @er6", "bior #7, @0xff40:8", "btst r0l, @er6",
    ),
    "control": (
        "nop", "stc ccr, r0l", "ldc r0l, ccr", "orc #0x01, ccr", "andc #0xfe, ccr",
        "bra LA\nLA:", "bne LA\nLA:", "beq LA\nLA:", "bra LA:16\nLA:", "brn LA\nLA:",
        "bsr LA\n    bra LB\nLA: rts\nLB:", "jsr @sub", "jsr @er4", "jmp @LA\nLA:",
        "stc ccr, @-er7\n    ldc @er7+, ccr", "mov.l #0xfb00, er6",
    ),
    "access": (
        "mov.b @0xf0e4, r1l", "mov.w @0xf0e0, r2", "mov.b @0xff9c, r0l", "mov.w @0xf0f6, r1",
        "mov.w @0xff98, r1", "mov.b @0xf0d0, r0l", "mov.w @0xf0d0, r1", "mov.w @0xffbc, r1",
        "mov.b @0xf067, r0l", "mov.b @0xffd4, r0l", "mov.b @0xfffa, r0l",
        "mov.b @0x0300, r0l", "mov.l @0x0300, er1", "mov.b @0xf0f3, r0l",
    ),
}


def program(templates):
    body = ["    bset #6, @0xfffb:8", "    sub.b r0l, r0l", "    mov.b r0l, @0xf0f1",
            "    mov.b r0l, @0xf0f2", "    mov.l #0xf0f0, er5", "    mov.l #sub, er4"]
    for index, text in enumerate(templates):
        for copies, slot in ((LONG, 0xF900), (SHORT, 0xF902)):
            body += ["    bclr #7, @er5", "    sub.w r0, r0", "    mov.w r0, @0xf0f6",
                     f"    mov.l #{SCRATCH:#x}, er6", "    bset #7, @er5"]
            for copy in range(copies):
                prefix = f"t{index}_{copies}_{copy}"
                body.append(f"{prefix}:\n    " + text.replace("LA", f"{prefix}a")
                            .replace("LB", f"{prefix}b"))
            body += [f"t{index}_{copies}_end:", "    bclr #7, @er5", "    mov.w @0xf0f6, r0",
                     f"    mov.w r0, @{slot:#x}"]
        body += ["    mov.w @0xf900, r0", "    mov.w @0xf902, r1", "    sub.w r1, r0",
                 f"    mov.w r0, @{0xF800 + 2 * index:#x}"]
    body += ["    mov.b #0xa5, r0l", "    mov.b r0l, @0xff20", "9:  bra 9b", "sub:", "    rts"]
    source = "\n".join([".vector 0, start", ".org 0x100", "start:", "    mov.l #0xff80, er7",
                        *body])
    listing = Listing()
    firmware, symbols = assemble(source, None, listing)
    return firmware, symbols, listing


def sequence_states(listing, symbols, index, text):
    """States of one copy, following the path taken (subroutine included)."""
    start = symbols[f"t{index}_{LONG}_0"]
    end = symbols[f"t{index}_{LONG}_1"]
    total = 0
    for entry in listing:
        pc, mnemonic, ops, _length = entry
        if start <= pc < end:
            data = SCRATCH + next((o[2] or 0 for o in ops if o[0] == "disp"), 0) \
                if any(o[0] in ("ind", "disp", "postinc", "predec") for o in ops) else None
            if mnemonic.startswith(("push", "pop", "stc", "ldc")) and "er7" in text:
                data = 0xFF7E
            total += timing.states(entry, data)
    if "jsr" in text:
        total += timing.states(next(e for e in listing if e[0] == symbols["sub"]))
    return total


def cases():
    evidence = {
        "kind": "documented",
        "source": "REJ09B0152-0300 Appendix A.3 (state formula), Table A.4 (I..N per form), "
                  "section 20.1 register access states (spec/register_access.tsv); "
                  "REJ09B0213-0300 §2.6",
        "question": "Does each instruction sequence take the states the manual gives, measured "
                    "as the difference of 40 and 8 copies against Timer W counting phi?",
        "limitation": "Code, stack and data are in on-chip memory. The differential method "
                      "cancels Timer W start/stop latency.",
    }
    for group, templates in GROUPS.items():
        firmware, symbols, listing = program(templates)
        records = b"".join(
            ((LONG - SHORT) * sequence_states(listing, symbols, i, t)).to_bytes(2, "big")
            for i, t in enumerate(templates))
        yield Case(f"timing-{group}", firmware, {"ram": {"f800": records.hex(), "ff20": "a5"}},
                   evidence=evidence, milliseconds=30)
