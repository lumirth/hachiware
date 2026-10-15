"""CCR transfer instructions, EEPMOV block moves, TRAPA and interrupt priority.

REJ09B0213-0300 §§2.2.5, 2.2.28, 2.2.34, 2.2.44, 2.2.58, 2.2.62 and 2.2.64
define the CCR instructions, EEPMOV and TRAPA. REJ09B0152-0300 Table 3.1 and
§3.4 give the vectors and the rule that the highest-priority pending request
is handled first; Figure 3.5 gives the normal-mode stack frame.
"""

from diagnostic import Case
from .asm import assemble
from .guest import image

SOFTWARE = ("REJ09B0213-0300 (H8/300H software manual): "
            "https://www.renesas.com/en/document/mah/h8300h-series-software-manual")
HARDWARE = ("REJ09B0152-0300 (H8/38602R group hardware manual): "
            "https://www.renesas.com/en/document/mah/h838602r-group-hardware-manual")
DONE = "    mov.b #0xa5, r0l\n    mov.b r0l, @0xff20"


def ccr_cases():
    rows, body = [], []
    values = (0x00, 0xFF, 0x5A, 0xA5, 0x0F, 0xF0)
    for first in values:
        for op, operand in (("ldc", 0x3C), ("ldcr", 0xC3), ("andc", 0x6E), ("orc", 0x91),
                            ("xorc", 0xFF), ("xorc", 0x55)):
            if op == "ldcr":
                line, result = f"    mov.b #{operand:#x}, r1l\n    ldc r1l, ccr", operand
            else:
                line = f"    {op} #{operand:#x}, ccr"
                result = {"ldc": operand, "andc": first & operand, "orc": first | operand,
                          "xorc": first ^ operand}[op]
            address = 0xF800 + len(rows)
            body.append(f"    ldc #{first:#x}, ccr\n{line}\n    stc ccr, r0l\n"
                        f"    mov.b r0l, @{address:#x}")
            rows.append(result)
    body.append(DONE)
    yield Case("isa-ccr-transfer", image("\n".join(body)),
               {"ram": {"f800": bytes(rows).hex(), "ff20": "a5"}},
               evidence={
                   "kind": "documented",
                   "source": SOFTWARE + " §§2.2.5, 2.2.34, 2.2.44, 2.2.58, 2.2.64",
                   "question": "Do LDC, ANDC, ORC and XORC replace or combine all eight CCR bits, "
                               "including the user bits, as STC reads them back?",
               }, milliseconds=10)


def eepmov_cases():
    evidence = {
        "kind": "documented",
        "source": SOFTWARE + " §2.2.28: byte-at-a-time @ER5+ → @ER6+ until the count is 0; "
                  "a zero count moves nothing; R4L/R4 end at 0 and ER5/ER6 at last address + 1; "
                  "no CCR change",
        "question": "Does EEPMOV move the counted bytes forward one at a time, leave the "
                    "registers at the documented end values and keep CCR?",
        "limitation": "An overlapping forward copy propagates the first byte because each byte "
                      "is read after the previous one is written.",
    }
    for width, count, overlap in (("b", 0, False), ("b", 1, False), ("b", 7, False),
                                  ("b", 255, False), ("w", 0, False), ("w", 1, False),
                                  ("w", 300, False), ("w", 520, False), ("b", 40, True),
                                  ("w", 600, True)):
        source, destination = 0xF880, (0xF881 if overlap else 0xFC00)
        length = max(count, 1) + 2
        pattern = bytes((i * 37 + 11) & 0xFF for i in range(700))
        memory = bytearray(0x800)  # 0xF800..0xFFFF model
        base = 0xF800
        body = [
            # Fill the source with the pattern and the destination with 0xEE.
            "    mov.l #0xf880, er1\n    mov.w #700, r2\n    mov.b #11, r0l\n"
            "1:  mov.b r0l, @er1\n    add.b #37, r0l\n    adds #1, er1\n    dec.w #1, r2\n"
            "    bne 1b",
        ]
        for i in range(700):
            memory[source - base + i] = pattern[i]
        if not overlap:
            body.append(f"    mov.l #{destination:#x}, er1\n    mov.w #{length:#x}, r2\n"
                        "    mov.b #0xee, r0l\n1:  mov.b r0l, @er1\n    adds #1, er1\n"
                        "    dec.w #1, r2\n    bne 1b")
            for i in range(length):
                memory[destination - base + i] = 0xEE
        r4 = (0x5A00 | count) if width == "b" else count
        body.append(f"    mov.l #{source:#x}, er5\n    mov.l #{destination:#x}, er6\n"
                    f"    mov.l #{0xC3C30000 | r4:#x}, er4\n    ldc #0x2b, ccr\n"
                    f"    eepmov.{width}\n    stc ccr, r0l\n    mov.b r0l, @0xf800\n"
                    "    mov.l er4, @0xf804\n    mov.l er5, @0xf808\n    mov.l er6, @0xf80c\n" + DONE)
        for i in range(count):
            memory[destination - base + i] = memory[source - base + i]
        end4 = (0xC3C35A00 if width == "b" else 0xC3C30000)
        header = bytes((0x2B, 0, 0, 0)) + end4.to_bytes(4, "big") \
            + (source + count).to_bytes(4, "big") + (destination + count).to_bytes(4, "big")
        start = destination - base
        observed = memory[start:start + length]
        name = f"isa-eepmov-{width}-{count}" + ("-overlap" if overlap else "")
        expected = {"f800": header[:1].hex(), "f804": header[4:].hex(),
                    f"{destination:04x}": observed.hex(), "ff20": "a5"}
        yield Case(name, image("\n".join(body)), {"ram": expected},
                   evidence=evidence, milliseconds=10)


def trapa_case():
    calls = [(n, ccr) for n in range(4) for ccr in (0x00, 0x4F, 0x31)]
    body = ["    mov.l #0xf800, er6"]
    for k, (n, ccr) in enumerate(calls):
        body.append(f"    ldc #{ccr:#x}, ccr\n    trapa #{n}\nret_{k}:\n    stc ccr, r0l\n"
                    "    mov.b r0l, @(3,er6)\n    add.l #6, er6")
    body.append(DONE + "\n9:  bra 9b")
    for n in range(4):
        body.append(f"trap_{n}:\n    stc ccr, r0l\n    mov.b #{n}, r1l\n    mov.b r1l, @er6\n"
                    "    mov.b r0l, @(1,er6)\n    mov.b @er7, r0l\n    mov.b r0l, @(2,er6)\n"
                    "    mov.w @(2,er7), r0\n    mov.w r0, @(4,er6)\n    rte")
    lines = [".vector 0, start"] + [f".vector {8 + n}, trap_{n}" for n in range(4)]
    lines += [".org 0x100", "start:", "    mov.l #0xff80, er7", *body]
    firmware, symbols = assemble("\n".join(lines))
    records = bytearray()
    for k, (n, ccr) in enumerate(calls):
        # UI is a user bit on this target, so TRAPA sets only I.
        records += bytes((n, ccr | 0x80, ccr, ccr)) + symbols[f"ret_{k}"].to_bytes(2, "big")
    yield Case("isa-trapa", firmware, {"ram": {"f800": records.hex(), "ff20": "a5"}},
               evidence={
                   "kind": "documented",
                   "source": SOFTWARE + " §2.2.62 (PC and CCR pushed, I set, UI unchanged when "
                             "used as a user bit); " + HARDWARE + " Table 3.1 (vectors 8-11), "
                             "Figure 3.5 (CCR at SP, PC at SP+2)",
                   "question": "Does TRAPA #0-3 take its own vector with the documented stack "
                               "frame and CCR, and does RTE restore the caller's CCR?",
               }, milliseconds=10)


PRIORITY_SETUP = {
    "tw": "    bset #6, @0xfffb:8\n    mov.b #0x80, r0l\n    mov.b r0l, @0xf0f1\n"
          "    mov.w #0x10, r0\n    mov.w r0, @0xf0f8\n    mov.b #1, r0l\n    mov.b r0l, @0xf0f2\n"
          "    mov.b #0x80, r0l\n    mov.b r0l, @0xf0f0\n"
          "1:  mov.b @0xf0f3, r0l\n    btst #0, r0l\n    beq 1b\n",
    "tb1": "    bset #2, @0xfffa:8\n    mov.b #0xbd, r0l\n    mov.b r0l, @0xf0d0\n"
           "    mov.b #0xf0, r0l\n    mov.b r0l, @0xf0d1\n    bset #2, @0xfff4:8\n"
           "    mov.b @0xf0d0, r0l\n    bset #6, r0l\n    mov.b r0l, @0xf0d0\n1:  btst #2, @0xfff7:8\n    beq 1b\n",
}


def priority_cases():
    handlers = (
        "tb1_isr:\n    bclr #2, @0xfff4:8\n    bclr #2, @0xfff7:8\n    mov.b #33, r0l\n"
        "    mov.b r0l, @er6\n    adds #1, er6\n    rte\n"
        "tw_isr:\n    sub.b r0l, r0l\n    mov.b r0l, @0xf0f2\n    mov.b r0l, @0xf0f0\n"
        "    mov.b @0xf0f3, r0l\n    bclr #0, r0l\n    mov.b r0l, @0xf0f3\n    mov.b #35, r0l\n    mov.b r0l, @er6\n    adds #1, er6\n"
        "    rte\n")
    for order in (("tw", "tb1"), ("tb1", "tw")):
        body = ("    mov.l #0xf800, er6\n    orc #0x80, ccr\n" + PRIORITY_SETUP[order[0]]
                + PRIORITY_SETUP[order[1]] + "    andc #0x7f, ccr\n    nop\n    nop\n"
                + DONE + "\n9:  bra 9b\n" + handlers)
        yield Case(f"interrupt-priority-{order[0]}-first", image(body, {33: "tb1_isr", 35: "tw_isr"}),
                   {"ram": {"f800": "2123", "ff20": "a5"}},
                   evidence={
                       "kind": "documented",
                       "source": HARDWARE + " §3.4 and Table 3.1 (Timer B1, vector 33, has higher "
                                 "priority than Timer W, vector 35)",
                       "question": "With both requests pending while I=1, is Timer B1 handled first "
                                   "whichever became pending first?",
                   }, milliseconds=10)


def cases():
    yield from ccr_cases()
    yield from eepmov_cases()
    yield from trapa_case()
    yield from priority_cases()
