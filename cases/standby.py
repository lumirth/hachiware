"""Peripheral clocks in sleep, watch and module standby; RTC flag write semantics.

REJ09B0152-0300 Table 5.3 lists Timer W as running in sleep mode and halted
(retained) in watch mode; §5.4 says module standby stops a module's clock;
§11.3.8 says an RTCFLG flag clears only when 0 is written to it. Each guest
reduces its measurement to a pass/fail byte with a wide margin, so the result
does not depend on exact wake-up latency.
"""

from diagnostic import Case
from .guest import image

HARDWARE = ("REJ09B0152-0300 (H8/38602R group hardware manual): "
            "https://www.renesas.com/en/document/mah/h838602r-group-hardware-manual")

TB1 = """
    bset #2, @0xfffa:8
    mov.b #0xbf, r0l
    mov.b r0l, @0xf0d0
    mov.b #0xf8, r0l
    mov.b r0l, @0xf0d1
    bclr #2, @0xfff7:8
    bset #2, @0xfff4:8
    mov.b @0xf0d0, r0l
    or.b #0x40, r0l
    mov.b r0l, @0xf0d0
"""
TIMER_W = """
    bset #6, @0xfffb:8
    mov.b #TCRW_VALUE, r0l
    mov.b r0l, @0xf0f1
    sub.b r0l, r0l
    mov.b r0l, @0xf0f2
    mov.b #0x80, r0l
    mov.b r0l, @0xf0f0
"""
ISR = "tb1_isr:\n    bclr #2, @0xfff7:8\n    rte\n"
DONE = "    mov.b #0xa5, r0l\n    mov.b r0l, @0xff20\n9:  bra 9b\n"


def mode_case(name, syscr1, syscr2, low, high, question, source):
    # Synchronise to a Timer B1 overflow in sleep mode, then sleep for one
    # 62.5 ms period in the mode under test and measure Timer W at phi/8.
    body = (TB1 + TIMER_W.replace("TCRW_VALUE", "0x30") + "    andc #0x7f, ccr\n"
            "    mov.b #0x07, r0l\n    mov.b r0l, @0xfff0:8\n    mov.b #0xe0, r0l\n"
            "    mov.b r0l, @0xfff1:8\n    sleep\n    mov.w @0xf0f6, r4\n"
            f"    mov.b #{syscr1:#x}, r0l\n    mov.b r0l, @0xfff0:8\n    mov.b #{syscr2:#x}, r0l\n"
            "    mov.b r0l, @0xfff1:8\n    sleep\n    mov.w @0xf0f6, r5\n    sub.w r4, r5\n"
            "    mov.w r5, @0xf802\n    sub.b r0l, r0l\n"
            f"    cmp.w #{low}, r5\n    bcs 1f\n    cmp.w #{high}, r5\n    bhi 1f\n"
            "    mov.b #1, r0l\n1:  mov.b r0l, @0xf800\n" + DONE + ISR)
    return Case(name, image(body, {33: "tb1_isr"}), {"ram": {"f800": "01", "ff20": "a5"}},
                evidence={"kind": "documented", "source": source, "question": question,
                          "limitation": "f802 holds the raw phi/8 count for diagnosis; only the "
                                        "range check at f800 is asserted."},
                milliseconds=300)


def cases():
    # One Timer B1 period is 2048 phiW clocks = 230400 states = 28800 phi/8 counts.
    yield mode_case(
        "power-sleep-timer-w-runs", 0x07, 0xE0, 28700, 28900,
        "Does Timer W keep counting phi/8 through a whole Timer B1 period in sleep mode?",
        HARDWARE + " Table 5.3 (sleep mode: Timer W functions), §9 (Timer B1 at phiW/256)")
    yield mode_case(
        "power-watch-timer-w-halted", 0xA7, 0xE0, 0, 7200,
        "Does Timer W stop in watch mode, so it counts far less than one Timer B1 period "
        "while the CPU sleeps in watch mode and wakes to active mode?",
        HARDWARE + " Table 5.3 (watch mode: Timer W retained, system clock halted), Table 5.2")

    body = (TIMER_W.replace("TCRW_VALUE", "0x00") + "    mov.w @0xf0f6, r4\n"
            "    bclr #6, @0xfffb:8\n    mov.w #1000, r1\n1:  dec.w #1, r1\n    bne 1b\n"
            "    bset #6, @0xfffb:8\n    mov.w @0xf0f6, r5\n    sub.w r4, r5\n"
            "    mov.w r5, @0xf802\n    sub.b r0l, r0l\n    cmp.w #300, r5\n    bcc 2f\n"
            "    mov.b #1, r0l\n2:  mov.b r0l, @0xf800\n" + DONE)
    yield Case("power-module-standby-timer-w", image(body), {"ram": {"f800": "01", "ff20": "a5"}},
               evidence={
                   "kind": "documented",
                   "source": HARDWARE + " §5.1.3 (TWCKSTP), §5.4 (module standby stops the "
                             "module clock)",
                   "question": "Does clearing TWCKSTP stop Timer W counting phi and setting it "
                               "resume from the retained count?",
                   "limitation": "The stopped interval is about 6000 states; only a count "
                                 "below 300 across it passes.",
               }, milliseconds=20)

    body = ("    bset #0, @0xfffa:8\n    mov.b #0x10, r0l\n    mov.b r0l, @0xf06c\n"
            "    sub.b r0l, r0l\n    mov.b r0l, @0xf06c\n    mov.b #0x08, r0l\n"
            "    mov.b r0l, @0xf06f\n    mov.b #0x01, r0l\n    mov.b r0l, @0xf06d\n"
            "    mov.b #0xc0, r0l\n    mov.b r0l, @0xf06c\n"
            "    sub.b r0l, r0l\n    mov.b r0l, @0xf067\n"
            "1:  mov.b @0xf067, r0l\n    btst #0, r0l\n    beq 1b\n"
            "    and.b #1, r0l\n    mov.b r0l, @0xf800\n"
            "    mov.b #0xff, r0l\n    mov.b r0l, @0xf067\n    mov.b @0xf067, r0l\n"
            "    and.b #1, r0l\n    mov.b r0l, @0xf801\n"
            "    mov.b #0xfe, r0l\n    mov.b r0l, @0xf067\n    mov.b @0xf067, r0l\n"
            "    and.b #1, r0l\n    mov.b r0l, @0xf802\n"
            "    mov.b #0x01, r0l\n    mov.b r0l, @0xf067\n    mov.b @0xf067, r0l\n"
            "    and.b #1, r0l\n    mov.b r0l, @0xf803\n" + DONE)
    yield Case("rtc-flag-write-semantics", image(body),
               {"ram": {"f800": "01010000", "ff20": "a5"}},
               evidence={
                   "kind": "documented",
                   "source": HARDWARE + " §11.3.6 (an enabled periodic interrupt sets its "
                             "flag), §11.3.8 (a flag clears when 0 is written to it while it is 1; "
                             "writing 1 has no effect). IENRTC stays 0 so no interrupt is taken.",
                   "question": "After the 0.25 s flag sets, does writing 1 leave it set, writing "
                               "0 clear it, and writing 1 again leave it clear?",
               }, milliseconds=400)
