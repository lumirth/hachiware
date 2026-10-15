"""Button levels on port B.

The retail InputScan (lumirth/pw) reads PDRB and treats bit 0 as the centre
button, bit 2 as left and bit 4 as right, with 1 meaning pressed. Port B is an
input-only port whose data register reads the pin levels (REJ09B0152-0300
§8.5). The guest samples PDRB once per millisecond, paced by Timer W
compare match A at phi, while the timeline presses and releases buttons
midway between samples.
"""

from diagnostic import Case
from .guest import image

BODY = """
    bset #6, @0xfffb:8
    mov.b #0x80, r0l
    mov.b r0l, @0xf0f1
    mov.w #3685, r0
    mov.w r0, @0xf0f8
    sub.b r0l, r0l
    mov.b r0l, @0xf0f2
    mov.b #0x80, r0l
    mov.b r0l, @0xf0f0
    mov.l #0xf800, er6
    mov.b #10, r3l
1:  mov.b @0xf0f3, r0l
    btst #0, r0l
    beq 1b
    bclr #0, r0l
    mov.b r0l, @0xf0f3
    mov.b @0xffde:8, r0l
    and.b #0x15, r0l
    mov.b r0l, @er6
    adds #1, er6
    dec.b r3l
    bne 1b
    mov.b #0xa5, r0l
    mov.b r0l, @0xff20
9:  bra 9b
"""

TIMELINE = ("2500,buttons,1,0,0\n4500,buttons,1,1,0\n6500,buttons,0,1,1\n"
            "8500,buttons,0,0,0\n")


def cases():
    yield Case("port-buttons-levels", image(BODY), {"ram": {"f800": "00000404050511110000",
                                                             "ff20": "a5"}},
               TIMELINE,
               evidence={
                   "kind": "software_reasoned",
                   "source": "lumirth/pw InputScan (PDRB bit 0 centre, bit 2 left, bit 4 right, "
                             "1 = pressed); REJ09B0152-0300 §8 (port B input data register), "
                             "§10.4.1 (compare match A clear for the 1 ms pacing)",
                   "question": "Does PDRB report each button's level while it is held and "
                               "clear it when released?",
                   "limitation": "Press polarity and bit assignment come from the firmware's "
                                 "reading of the board, not a measurement.",
               }, milliseconds=15)
