"""Code rewritten in RAM between executions.

The H8/38606F executes code from on-chip RAM. A store completes before the
next instruction is fetched past the prefetch, so a routine rewritten and then
called runs the new bytes. Each guest calls a routine at 0xFC00 many times,
rewriting it in a different way, and records the sum the executions produce.
An emulator that caches decoded or translated code without noticing the
stores runs stale code and reports a different sum.
"""

from diagnostic import Case

from .guest import image

ROUTINE = 0xFC00
COUNT = 400


def copy_routine(words: list[int]) -> str:
    lines = [f"    mov.w #{w:#06x}, r0\n    mov.w r0, @{ROUTINE + 2 * i:#x}"
             for i, w in enumerate(words)]
    return "\n".join(lines)


def finish() -> str:
    return "    mov.w r1, @0xf780\n    mov.b #0xa5, r0l\n    mov.b r0l, @0xf782\n"


def cases():
    evidence = {
        "kind": "documented",
        "source": "REJ09B0152-0300 §2 (instruction execution from on-chip RAM, prefetch), "
                  "§2.8; H8/300H software manual instruction encodings",
        "question": "Does code rewritten in RAM between calls execute as rewritten?",
        "limitation": "Every rewrite is followed by a call, so no rewritten instruction is "
                      "already prefetched; prefetch itself is tested by other cases.",
    }
    variants = []

    # ADD.W #imm,R1 (79 11 imm) with the immediate rewritten before every call.
    body = copy_routine([0x7911, 0x0000, 0x5470]) + f"""
    sub.w r1, r1
    mov.w #1, r4
1:  mov.w r4, @{ROUTINE + 2:#x}
    jsr @{ROUTINE:#x}
    inc.w #1, r4
    cmp.w #{COUNT + 1}, r4
    bne 1b
""" + finish()
    variants.append(("immediate", body, sum(range(1, COUNT + 1)) & 0xFFFF))

    # The operation byte alternates between ADD.W (79 1r) and SUB.W (79 3r).
    body = copy_routine([0x7911, 0x0101, 0x5470]) + f"""
    sub.w r1, r1
    mov.w #{COUNT}, r4
1:  mov.b r4l, r0l
    and.b #1, r0l
    shll.b r0l
    shll.b r0l
    shll.b r0l
    shll.b r0l
    shll.b r0l
    or.b #0x11, r0l
    mov.b r0l, @{ROUTINE + 1:#x}
    jsr @{ROUTINE:#x}
    dec.w #1, r4
    bne 1b
""" + finish()
    total = 0
    for i in range(COUNT, 0, -1):
        total += -0x101 if i & 1 else 0x101
    variants.append(("operation", body, total & 0xFFFF))

    # Whole instruction rewritten with MOV.L: INC.W #1,R1 (0b51) or #2 (0bd1),
    # followed by a NOP, chosen from the loop count.
    body = copy_routine([0x0b51, 0x0000, 0x5470]) + f"""
    sub.w r1, r1
    mov.w #{COUNT}, r4
1:  mov.l #0x0b510000, er0
    btst #1, r4l
    beq 2f
    mov.l #0x0bd10000, er0
2:  mov.l er0, @{ROUTINE:#x}
    jsr @{ROUTINE:#x}
    dec.w #1, r4
    bne 1b
""" + finish()
    total = sum(2 if i & 2 else 1 for i in range(COUNT, 0, -1))
    variants.append(("long-store", body, total & 0xFFFF))

    # A branch displacement selects one of three tails: +1, +3 or +7.
    tails = [0x4000, 0x0b51, 0x5470, 0x0bd1, 0x0b51, 0x5470, 0x0bd1, 0x0bd1, 0x0bd1,
             0x0b51, 0x5470]
    body = copy_routine(tails) + f"""
    sub.w r1, r1
    mov.w #{COUNT}, r4
1:  mov.b r4l, r0l
    and.b #3, r0l
    beq 3f
    cmp.b #1, r0l
    beq 4f
    mov.b #0x0a, r0l
    bra 5f
3:  sub.b r0l, r0l
    bra 5f
4:  mov.b #4, r0l
5:  mov.b r0l, @{ROUTINE + 1:#x}
    jsr @{ROUTINE:#x}
    dec.w #1, r4
    bne 1b
""" + finish()
    total = sum({0: 1, 1: 3}.get(i & 3, 7) for i in range(COUNT, 0, -1))
    variants.append(("branch", body, total & 0xFFFF))

    # A hot routine runs 3000 times unchanged, then once rewritten by a byte
    # store to its immediate, then again unchanged at the new value.
    body = copy_routine([0x7911, 0x0001, 0x5470]) + """
    sub.w r1, r1
    mov.w #3000, r4
1:  jsr @0xfc00
    dec.w #1, r4
    bne 1b
    mov.b #0x10, r0l
    mov.b r0l, @0xfc03
    mov.w #10, r4
2:  jsr @0xfc00
    dec.w #1, r4
    bne 2b
""" + finish()
    variants.append(("hot", body, (3000 + 10 * 0x10) & 0xFFFF))

    for name, text, value in variants:
        yield Case(f"code-rewrite-{name}", image(text),
                   {"ram": {"f780": f"{value:04x}a5"}}, evidence=evidence, milliseconds=60)
