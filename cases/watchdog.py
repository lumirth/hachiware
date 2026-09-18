"""Watchdog write qualification and the alignment erratum."""

from diagnostic import Case
from .h8 import Program


def cases():
    basis = {
        "kind": "documented",
        "source": "REJ09B0152-0300 §12.2; TN-H8*-A309B/E rev.2 (2005-10-04)",
        "question": "Do old-latch protection, actual MOV.B addressing/alignment, and OVF read "
        "qualification preserve each independent register field?",
        "limitation": "Alignment assertions use the absolute-8 MOV.B form shown in the erratum; other "
        "MOV.B forms follow ordinary write qualification.",
    }

    # REJ09B0152-0300 §12.2 and TN-H8*-A309B/E. These are register
    # observations by original guest code, with explicit instruction alignment.
    def record(p, address, slot):
        p.code += bytes(
            (0x6A, 0x08, address >> 8, address & 255, 0x6A, 0x88, 0xF8, slot)
        )

    p = Program()
    for i, a in enumerate(range(0xFFB0, 0xFFB4)):
        record(p, a, i)
    for i, v in enumerate([0x12, 0xA2, 0x8E], 4):
        p.byte(0xFFB1, v)
        record(p, 0xFFB1, i)
    p.byte(0xFFB3, 0x55)
    record(p, 0xFFB3, 7)
    p.byte(0xFFB1, 0x5E)
    record(p, 0xFFB1, 8)
    p.byte(0xFFB3, 0xC3)
    record(p, 0xFFB3, 9)
    yield Case(
        "watchdog-qualified-controls",
        p.finish(),
        {"ram": {"f800": "f0ae5700beba aa00fac3".replace(" ", "")}},
        None,
        evidence=basis,
    )

    p = Program()
    for v in [0x9E, 0xA2, 0x8E]:
        p.byte(0xFFB1, v)
    slot = 0
    for clear in [0x87, 0xC7, 0x97]:
        p.byte(0xFFB2, 0x28)
        record(p, 0xFFB2, slot)
        slot += 1
        for pc_bit1 in [0, 2]:
            p.code += bytes((0xF8, clear))
            if (0x100 + len(p.code)) & 2 != pc_bit1:
                p.code += bytes(2)
            p.code += bytes.fromhex("38b2")
            record(p, 0xFFB2, slot)
            slot += 1
    p.byte(0xFFB2, 0x28)
    p.word(0xFFB2, 0x8700)
    record(p, 0xFFB2, 9)
    p.byte(0xFFB2, 0x87)
    record(p, 0xFFB2, 10)
    yield Case(
        "watchdog-interval-clear-alignment",
        p.finish(),
        {"ram": {"f800": "7f7f577f7f777f7f5f7f57"}},
        None,
        evidence=basis,
    )

    p = Program()
    for a, v in [(0xFFB1, 0x5E), (0xFFB3, 0xFF), (0xFFB2, 0x28), (0xFFFB, 0)]:
        p.byte(a, v)
    record(p, 0xFFB2, 0)  # Reads OVF=0 before the first ROSC/2048 edge.
    p.code += bytes(8000)  # Four thousand NOPs: beyond the first 1.5625-ms edge.
    p.byte(0xFFB2, 0x7F)  # That old read of zero cannot clear a new OVF.
    record(p, 0xFFB2, 1)
    p.byte(0xFFB2, 0x7F)
    record(p, 0xFFB2, 2)
    yield Case(
        "watchdog-overflow-read-qualification",
        p.finish(),
        {"ram": {"f800": "7fff7f"}},
        None,
        evidence=basis,
    )
