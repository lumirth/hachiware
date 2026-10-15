"""Timer B1 prescalers and modes, Timer W compare match, clear and overflow.

Timer W counting phi measures the time between two Timer B1 overflows found
by polling IRR2, and the TCNT value just after a Timer W flag is found. The
polling loop adds at most a few tens of states, far less than the differences
between prescaler settings, so each guest asserts a range check byte and
keeps the raw count beside it for diagnosis.
"""

from diagnostic import Case
from .guest import image

HARDWARE = ("REJ09B0152-0300 (H8/38602R group hardware manual): "
            "https://www.renesas.com/en/document/mah/h838602r-group-hardware-manual")
SLACK = 40
DONE = "    mov.b #0xa5, r0l\n    mov.b r0l, @0xff20\n9:  bra 9b\n"
FREE_RUN = ("    bset #6, @0xfffb:8\n    sub.b r0l, r0l\n    mov.b r0l, @0xf0f1\n"
            "    mov.b r0l, @0xf0f2\n    mov.b #0x80, r0l\n    mov.b r0l, @0xf0f0\n")
POLL_TB1 = "1:  mov.b @0xfff7, r0l\n    btst #2, r0l\n    beq 1b\n    bclr #2, @0xfff7:8\n"


def check(register, low, high, flag):
    return (f"    sub.b r0l, r0l\n    cmp.w #{low}, {register}\n    bcs 3f\n"
            f"    cmp.w #{high}, {register}\n    bhi 3f\n    mov.b #1, r0l\n"
            f"3:  mov.b r0l, @{flag:#x}\n")


def b1_cases():
    evidence = {
        "kind": "documented",
        "source": HARDWARE + " §9.2.1 (TMB1 clock select), §9.4.1 (interval: overflow from "
                  "H'FF to H'00), §9.4.2 (auto-reload: TLB1 loaded at overflow)",
        "question": "Is the Timer B1 overflow period the selected phi divisor times the "
                    "number of counts from the reload value (auto-reload) or 256 (interval)?",
        "limitation": "Measured between two polled overflows with Timer W at phi; the "
                      f"check allows ±{SLACK} states. f802 holds the raw count.",
    }
    for cks, divisor in ((5, 4), (4, 16), (3, 64), (2, 256)):
        for reload in (True, False):
            if not reload and divisor > 16:
                continue
            counts = 64 if reload else 256
            period = counts * divisor
            tmb = (0x80 if reload else 0) | 0x38 | cks
            body = (FREE_RUN + "    bset #2, @0xfffa:8\n"
                    f"    mov.b #{tmb:#x}, r0l\n    mov.b r0l, @0xf0d0\n"
                    "    mov.b #0xc0, r0l\n    mov.b r0l, @0xf0d1\n"
                    f"    mov.b #{tmb | 0x40:#x}, r0l\n    mov.b r0l, @0xf0d0\n"
                    # Discard the first overflow; time the next two.
                    + POLL_TB1 + POLL_TB1.replace("1:", "4:").replace("1b", "4b")
                    + "    mov.w @0xf0f6, r4\n"
                    + POLL_TB1.replace("1:", "5:").replace("1b", "5b")
                    + "    mov.w @0xf0f6, r5\n    sub.w r4, r5\n    mov.w r5, @0xf802\n"
                    + check("r5", period - SLACK, period + SLACK, 0xF800) + DONE)
            mode = "reload" if reload else "interval"
            yield Case(f"timer-b1-period-phi{divisor}-{mode}", image(body),
                       {"ram": {"f800": "01", "ff20": "a5"}}, evidence=evidence,
                       milliseconds=20)


def w_cases():
    evidence = {
        "kind": "documented",
        "source": HARDWARE + " §10.3.2 (TCRW CCLR), §10.3.4 (TSRW flags), §10.4.1 (normal "
                  "operation: compare match sets IMFx when TCNT equals GRx; overflow sets OVF "
                  "on H'FFFF to H'0000; CCLR clears TCNT on compare match A)",
        "question": "Do compare match B, compare match A with counter clear and overflow set "
                    "their flags at the documented counts?",
        "limitation": "TCNT is read a few tens of states after the flag is found; the check "
                      f"allows {SLACK} counts at phi. Raw counts are at f804-f809.",
    }
    body = (
        # Compare match B on a free-running counter.
        "    bset #6, @0xfffb:8\n    sub.b r0l, r0l\n    mov.b r0l, @0xf0f1\n"
        "    mov.b r0l, @0xf0f2\n    mov.w #0x4000, r0\n    mov.w r0, @0xf0fa\n"
        "    mov.w #0xffff, r0\n    mov.w r0, @0xf0f8\n    sub.w r0, r0\n    mov.w r0, @0xf0f6\n"
        "    mov.b @0xf0f3, r0l\n    and.b #0x70, r0l\n    mov.b r0l, @0xf0f3\n"
        "    mov.b #0x80, r0l\n    mov.b r0l, @0xf0f0\n"
        "1:  mov.b @0xf0f3, r0l\n    btst #1, r0l\n    beq 1b\n    mov.w @0xf0f6, r4\n"
        "    mov.w r4, @0xf804\n"
        + check("r4", 0x4000, 0x4000 + SLACK, 0xF800) +
        # Compare match A with clear: TCNT restarts from 0 after GRA.
        "    mov.b #0x80, r0l\n    mov.b r0l, @0xf0f1\n    mov.w #0x2000, r0\n"
        "    mov.w r0, @0xf0f8\n    sub.w r0, r0\n    mov.w r0, @0xf0f6\n"
        "    mov.b @0xf0f3, r0l\n    and.b #0x70, r0l\n    mov.b r0l, @0xf0f3\n"
        "2:  mov.b @0xf0f3, r0l\n    btst #0, r0l\n    beq 2b\n    mov.w @0xf0f6, r4\n"
        "    mov.w r4, @0xf806\n"
        + check("r4", 0, SLACK, 0xF801).replace("3f", "6f").replace("3:", "6:") +
        # Overflow without clearing.
        "    sub.b r0l, r0l\n    mov.b r0l, @0xf0f1\n    mov.w #0xff00, r0\n    mov.w r0, @0xf0f6\n"
        "    mov.b @0xf0f3, r0l\n    and.b #0x70, r0l\n    mov.b r0l, @0xf0f3\n"
        "4:  mov.b @0xf0f3, r0l\n    btst #7, r0l\n    beq 4b\n    mov.w @0xf0f6, r4\n"
        "    mov.w r4, @0xf808\n"
        + check("r4", 0, SLACK, 0xF802).replace("3f", "7f").replace("3:", "7:") + DONE)
    yield Case("timer-w-compare-clear-overflow", image(body),
               {"ram": {"f800": "010101", "ff20": "a5"}}, evidence=evidence, milliseconds=60)


def cases():
    yield from b1_cases()
    yield from w_cases()
