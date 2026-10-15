"""CPU clock in active medium-speed and subactive modes.

REJ09B0152-0300 §5.1.1 (MA1/MA0: phiOSC/8 to /64), §5.1.2 (MSON selects
active medium-speed after sleep mode ends; SA1/SA0: phiW/8 to phiW) and
Table 5.2. Each guest wakes into the mode under test on a Timer B1 interrupt,
then counts iterations of a 14-state polling loop over one Timer B1 period of
2048 phiW clocks. The check allows 3% plus two iterations.
"""

from diagnostic import Case
from .guest import image

HARDWARE = ("REJ09B0152-0300 (H8/38602R group hardware manual): "
            "https://www.renesas.com/en/document/mah/h838602r-group-hardware-manual")
PHI_OSC, PHI_W, PERIOD_W = 3_686_400, 32_768, 2048
LOOP = 14  # ADDS 2, MOV.B @aa:16 6, BTST 2, BEQ 4 (Table A.4)

SETUP = """
    bset #2, @0xfffa:8
    mov.b #0xbf, r0l
    mov.b r0l, @0xf0d0
    mov.b #0xf8, r0l
    mov.b r0l, @0xf0d1
    bclr #2, @0xfff7:8
    bset #2, @0xfff4:8
    mov.b #0xff, r0l
    mov.b r0l, @0xf0d0
    andc #0x7f, ccr
"""
COUNT = """
    bclr #2, @0xfff4:8
1:  mov.b @0xfff7, r0l
    btst #2, r0l
    beq 1b
    bclr #2, @0xfff7:8
    sub.l er4, er4
2:  adds #1, er4
    mov.b @0xfff7, r0l
    btst #2, r0l
    beq 2b
    mov.w r4, @0xf802
    sub.b r0l, r0l
    cmp.w #LOW, r4
    bcs 3f
    cmp.w #HIGH, r4
    bhi 3f
    mov.b #1, r0l
3:  mov.b r0l, @0xf800
    mov.b #0xa5, r0l
    mov.b r0l, @0xff20
9:  bra 9b
tb1_isr:
    bclr #2, @0xfff7:8
    rte
"""


def guest(syscr1, syscr2, states_per_period):
    expected = states_per_period / LOOP
    low, high = int(expected * 0.97) - 2, int(expected * 1.03) + 2
    body = (SETUP + f"    mov.b #{syscr1:#x}, r0l\n    mov.b r0l, @0xfff0:8\n"
            f"    mov.b #{syscr2:#x}, r0l\n    mov.b r0l, @0xfff1:8\n    sleep\n"
            + COUNT.replace("LOW", str(max(low, 0))).replace("HIGH", str(high)))
    return image(body, {33: "tb1_isr"})


def cases():
    for ma, divisor in ((0, 8), (1, 16), (2, 32), (3, 64)):
        states = PERIOD_W * PHI_OSC / PHI_W / divisor
        yield Case(f"power-speed-medium-{divisor}", guest(ma, 0xE4, states),
                   {"ram": {"f800": "01", "ff20": "a5"}},
                   evidence={
                       "kind": "documented",
                       "source": HARDWARE + " §5.1.1 MA1/MA0, §5.1.2 MSON, Table 5.2 (sleep "
                                 "mode ends into active medium-speed when MSON = 1)",
                       "question": f"After waking with MSON = 1 and MA = {ma:02b}, does the CPU run "
                                   f"at phiOSC/{divisor} against Timer B1 on phiW?",
                       "limitation": "f802 holds the raw iteration count.",
                   }, milliseconds=250)
    for sa, divisor in ((0, 8), (1, 4), (2, 2), (3, 1)):
        states = PERIOD_W / divisor
        yield Case(f"power-speed-subactive-{divisor}", guest(0xAF, 0xE0 | sa, states),
                   {"ram": {"f800": "01", "ff20": "a5"}},
                   evidence={
                       "kind": "documented",
                       "source": HARDWARE + " §5.1.1 LSON/TMA3, §5.1.2 SA1/SA0, Table 5.2 "
                                 "(watch mode ends into subactive mode when LSON = 1)",
                       "question": f"Does subactive mode with SA = {sa:02b} run the CPU at "
                                   f"phiW/{divisor}?",
                       "limitation": "Coarse at phiW/8 (about 18 iterations); f802 holds the "
                                     "raw count.",
                   }, milliseconds=250)
