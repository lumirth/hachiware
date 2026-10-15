"""Interrupts taken while the CPU polls a peripheral flag.

Timer W counts phi/8 and clears on compare match A every PERIOD counts. The
main loop polls IMFA with interrupts enabled; compare match B, at a phase
inside the period, requests an interrupt whose handler first reads TCNT. The
handler must run once per period, and each TCNT it reads must follow the
match by the interrupt response time (REJ09B0152-0300 §3.4.3: completion of
the current instruction, PC/CCR stacking, vector fetch and refill; at most
about 30 states with this loop's short instructions), allowing one count of
prescaler phase. The guest counts in-window readings itself. A target that
advances time through a polling loop without delivering the interrupt when
it is requested, or that delivers it late, fails.
"""

from diagnostic import Case

from .guest import image

PERIOD = 1000
PERIODS = 8

POLLS = {
    "register": "1:  mov.b @0xf0f3, r0l\n    btst #0, r0l\n    beq 1b\n",
    "bit": "    mov.l #0xf0f3, er1\n1:  btst #0, @er1\n    beq 1b\n    mov.b @0xf0f3, r0l\n",
    "word": "1:  mov.w @0xf0f2, r0\n    btst #0, r0l\n    beq 1b\n",
}


def guest(poll: str, compare_b: int) -> bytes:
    low, high = compare_b + 1, compare_b + 6
    return image(f"""
    bset #6, @0xfffb:8
    mov.b #0xb0, r0l
    mov.b r0l, @0xf0f1
    mov.w #{PERIOD - 1}, r0
    mov.w r0, @0xf0f8
    mov.w #{compare_b}, r0
    mov.w r0, @0xf0fa
    sub.w r0, r0
    mov.w r0, @0xf0f6
    mov.w r0, @0xf780
    mov.l #0xf790, er3
    mov.l er3, @0xf786
    mov.b #2, r0l
    mov.b r0l, @0xf0f2
    sub.w r4, r4
    mov.b #0x80, r0l
    mov.b r0l, @0xf0f0
    andc #0x7f, ccr
main:
{POLLS[poll]}    bclr #0, r0l
    mov.b r0l, @0xf0f3
    inc.w #1, r4
    cmp.w #{PERIODS}, r4
    bne main
    orc #0x80, ccr
    mov.w r4, @0xf782
    ; Count handler readings inside the response window.
    mov.l #0xf790, er3
    sub.w r1, r1
    mov.w @0xf780, r2
    beq 3f
2:  mov.w @er3+, r0
    sub.w #{low}, r0
    cmp.w #{high - low}, r0
    bhi 4f
    inc.w #1, r1
4:  dec.w #1, r2
    bne 2b
3:  mov.w r1, @0xf784
    mov.b #0xa5, r0l
    mov.b r0l, @0xf78a
    bra done

isr:
    mov.w @0xf0f6, r5
    mov.l @0xf786, er6
    mov.w r5, @er6
    adds #2, er6
    mov.l er6, @0xf786
    mov.w @0xf780, r6
    inc.w #1, r6
    mov.w r6, @0xf780
    mov.b @0xf0f3, r6l
    bclr #1, r6l
    mov.b r6l, @0xf0f3
    rte
""", {35: "isr"})


def cases():
    evidence = {
        "kind": "documented",
        "source": "REJ09B0152-0300 §10 (Timer W compare match, counter clear, IMFA/IMFB "
                  "clearing), §3.4 (interrupt exception handling and response time), "
                  "Table A.4",
        "question": "Is a Timer W interrupt delivered on time while the CPU polls another "
                    "Timer W flag?",
        "limitation": "The window allows the response time of the loop's instructions plus "
                      "one count of prescaler phase either way; f790.. holds the raw readings.",
    }
    for poll in POLLS:
        for compare_b in (137, 862):
            yield Case(f"poll-interrupt-{poll}-{compare_b}", guest(poll, compare_b),
                       {"ram": {"f780": f"{PERIODS:04x}{PERIODS:04x}{PERIODS:04x}",
                                "f786": f"{0xF790 + 2 * PERIODS:08x}", "f78a": "a5"}},
                       evidence=evidence, milliseconds=30)
