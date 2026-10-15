"""Timing witnesses: guest-measured durations with windows from the manual.

A witness times straight-line code with Timer W counting phi. The expected count
is the Table A.4 state sum of the timed instructions plus the part of the
stopping BCLR before its write cycle; the window allows WINDOW_STATES for
counter start and stop synchronization. An emulator that executes instructions
in the wrong number of states, or runs the CPU and Timer W on unrelated clocks,
reports a count outside the window.
"""

from __future__ import annotations

import random

from cases import timing

WINDOW_STATES = 8
SCRATCH = 0xFB00

# Straight-line instruction templates. {d} is an even displacement into the
# scratch block addressed by er6, {i} an immediate, {b} a bit number.
TEMPLATES = (
    "mov.b @er6, r0l", "mov.w @({d},er6), r1", "mov.l @({d},er6), er2",
    "mov.b r0l, @({d},er6)", "mov.w r1, @({d},er6)", "mov.l er2, @({d},er6)",
    "mov.w @0xfb40, r3", "mov.b r3l, @0xfb41", "mov.b @0xffde:8, r0h",
    "mov.b @0xf0e4, r1l", "mov.w @0xf0e0, r2", "mov.b #{i}, r0l", "mov.w #{i}, r1",
    "mov.l #{i}, er3", "add.b r0l, r1h", "add.w r1, r2", "add.l er2, er3",
    "add.b #{i}, r0h", "add.w #{i}, r3", "add.l #{i}, er2", "sub.w r3, r1",
    "sub.l er1, er2", "cmp.b r0l, r1l", "cmp.w #{i}, r2", "cmp.l er2, er3",
    "and.b #{i}, r1l", "or.w r2, r3", "xor.l er1, er3", "not.b r0h", "neg.w r1",
    "inc.b r2l", "dec.w #1, r3", "inc.l #2, er1", "adds #4, er2", "subs #2, er3",
    "shll.b r0l", "shar.w r1", "rotxl.l er2", "rotr.b r3h", "shlr.l er3",
    "exts.w r2", "extu.l er1", "mulxu.b r0l, r1", "mulxs.w r3, er2",
    "bset #{b}, r0l", "bclr #{b}, r1h", "bnot #{b}, r2l", "btst #{b}, r3l",
    "bld #{b}, r0h", "bst #{b}, r1l", "bxor #{b}, r2h", "bset #{b}, @er6",
    "btst #{b}, @0xffde:8", "stc ccr, r0l", "nop", "push.w r1\n    pop.w r1",
    "push.l er2\n    pop.l er2", "daa r0l", "das r1l", "bra 1f\n1:", "bne 1f\n1:",
    "beq 1f\n1:", "mov.b #3, r0l\n    divxu.b r0l, r1", "mov.w #7, r3\n    divxs.w r3, er2",
)


# The subset whose instruction forms appear in compiled retail firmware code.
FIRMWARE_TEMPLATES = tuple(t for t in TEMPLATES if not any(
    t.startswith(prefix) for prefix in (
        "rotxl", "rotr", "bnot", "bxor", "btst #{b}, @", "stc", "daa", "das", "inc.l #2")))


def block(seed: int, count: int, templates: tuple[str, ...] = FIRMWARE_TEMPLATES) -> str:
    """A reproducible straight-line block of ``count`` templates."""
    rng = random.Random(seed)
    lines = []
    for _ in range(count):
        text = rng.choice(templates)
        text = text.format(
            d=rng.randrange(0, 0x40, 2), i=rng.randrange(1, 0x7F), b=rng.randrange(8)
        )
        lines.append("    " + text)
    return "\n".join(lines)


def timed(label: str, seed: int, count: int, result: int,
          templates: tuple[str, ...] = FIRMWARE_TEMPLATES) -> str:
    """Time a generated block with Timer W at phi and store TCNT at ``result``.

    The labels ``{label}_start`` and ``{label}_end`` delimit the timed code.
    Use-tier workloads time only instruction forms of compiled retail code, so
    an emulator is not failed on a use-tier workload for forms firmware never
    executes; those forms are scored by the conformance cases.
    """
    return f"""
    bset #6, @CKSTPR2:8
    mov.l #TMRW, er5
    bclr #7, @er5
    sub.b r0l, r0l
    mov.b r0l, @TCRW
    mov.b r0l, @TIERW
    sub.w r0, r0
    mov.w r0, @TCNT
    mov.l #{SCRATCH:#x}, er6
    bset #7, @er5
{label}_start:
{block(seed, count, templates)}
{label}_end:
    bclr #7, @er5
    mov.w @TCNT, r0
    mov.w r0, @{result:#x}
"""


def window(listing, symbols: dict, label: str) -> tuple[int, int]:
    """Expected TCNT range for a block placed by ``timed``."""
    start, end = symbols[f"{label}_start"], symbols[f"{label}_end"]
    overrides = {}
    for pc, mnemonic, ops, _length in listing:
        if start <= pc < end and any(o[0] in ("ind", "disp") for o in ops):
            overrides[pc] = SCRATCH
    states = timing.span(listing, start, end, overrides)
    stop = next(e for e in listing if e[0] == end)
    # BCLR #n,@ERd: two fetch words and the read precede the write cycle.
    before_write = timing.states(stop, 0xF0F0) - timing.access_states(0xF0F0, 1)
    nominal = states + before_write
    return nominal - WINDOW_STATES, nominal + WINDOW_STATES


def sampled(label: str, seed: int, count: int, result: int,
            templates: tuple[str, ...] = FIRMWARE_TEMPLATES) -> str:
    """Time a block by reading a free-running TCNT (phi/8) before and after.

    Timer W must already count at phi/8 and not reach its compare value during
    the block. The difference of the two reads is stored at ``result``. Uses
    r4, r5 and er6.
    """
    return f"""
    mov.l #{SCRATCH:#x}, er6
    mov.w @TCNT, r4
{label}_start:
{block(seed, count, templates)}
{label}_end:
    mov.w @TCNT, r5
    sub.w r4, r5
    mov.w r5, @{result:#x}
"""


def sampled_window(listing, symbols: dict, label: str) -> tuple[int, int]:
    """Expected phi/8 count difference for a block placed by ``sampled``.

    The reads sample TCNT at their last cycle, so the interval is the block
    plus the second read up to its data cycle. Counting at phi/8 from an
    unknown prescaler phase adds up to one count either way.
    """
    start, end = symbols[f"{label}_start"], symbols[f"{label}_end"]
    overrides = {pc: SCRATCH for pc, _m, ops, _l in listing
                 if start <= pc < end and any(o[0] in ("ind", "disp") for o in ops)}
    second = next(e for e in listing if e[0] == end)
    tcnt = 0xF0F6
    nominal = (timing.span(listing, start, end, overrides)
               + timing.states(second, tcnt) - timing.access_states(tcnt, 2))
    return (nominal - WINDOW_STATES) // 8, -(-(nominal + WINDOW_STATES) // 8)
