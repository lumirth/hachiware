"""Buzzer: score playback on Timer W, as the firmware plays jingles and alerts.

The Pokewalker plays short tunes on its piezo buzzer: a jingle on connection,
level-up and reward sounds, menu and alarm tones. The firmware drives them from
Timer W in PWM mode on the watch clock (lumirth/pw BeepEnableTimer, BeepSetPeriod,
BeepAdvance, TimerWInterrupt): each note sets GRA to a compare value, the
compare-match A interrupt fires once per (GRA+1) watch clocks, counts down the
note's periods and advances to the next note, and the CPU sleeps between
interrupts. A 16 Hz Timer B1 tick paces the device, and both timers run from the
32.768 kHz watch clock.

Each 2 s pass plays one seeded melody of NOTES notes to completion and then goes
quiet until the next pass, a burst-then-silence shape like a real jingle. The
pass is observed in the quiet gap after the melody, so the counts do not depend
on where in a note the observation falls. The melody's own compare-match count
(periods) checks that the emulator runs the PWM at the right cadence, and the
number of Timer B1 ticks the melody spans checks its rate: Timer W and Timer B1
both divide the watch clock, so a correct core spans a fixed number of B1 ticks
however fast it runs in host time, while a core that runs Timer W at the wrong
rate relative to the watch clock spans the wrong number.
"""

from __future__ import annotations

import random

from cases.asm import Listing

from ..runtime import RESULTS, program
from ..workload import Paced, Workload, u16

NOTES = 20
B1_CLOCKS = 2048  # Timer B1 period: watch clock / 16.

GUEST = r"""
TICKS = 0xf820
SEEN = 0xf821
PLAYING = 0xf822
NOTEIDX = 0xf823
REMAIN = 0xf824
SSTART = 0xf826
RES = 0xf780
R_SCORES = 0xf780
R_NOTES = 0xf782
R_PERIODS = 0xf784
R_LASTPITCH = 0xf786
R_B1MIN = 0xf788
R_B1MAX = 0xf78a

    jsr @wdt_start
    jsr @hw_setup
    jsr @tb1_init
    jsr @rtc_init
    sub.w r0, r0
    mov.b r0l, @TICKS
    mov.b r0l, @SEEN
    mov.b r0l, @PLAYING
    mov.w r0, @R_SCORES
    mov.w r0, @R_NOTES
    mov.w r0, @R_PERIODS
    mov.w r0, @R_LASTPITCH
    mov.w r0, @R_B1MAX
    mov.w #0xffff, r0
    mov.w r0, @R_B1MIN
    andc #0x7f, ccr
main:
    mov.b @PLAYING, r0l
    bne 1f
    jsr @sleep_watch_active
    jsr @wdt_kick
    mov.b @TICKS, r0l
    mov.b @SEEN, r0h
    cmp.b r0l, r0h
    beq main
    mov.b r0l, @SEEN
    and.b #31, r0l
    bne main
    jsr @start_score
    bra main
1:  jsr @sleep_idle
    jsr @wdt_kick
    bra main

; Load note NOTEIDX: set GRA and the half-value B/C compares and REMAIN.
load_note:
    sub.l er3, er3
    mov.b @NOTEIDX, r3l
    shll.b r3l
    mov.b @(notes,er3), r0l
    sub.b r0h, r0h
    mov.w r0, @GRA
    shlr.w r0
    mov.w r0, @GRB
    mov.w r0, @GRC
    inc.b r3l
    mov.b @(notes,er3), r0l
    sub.b r0h, r0h
    mov.w r0, @REMAIN
    rts

; Begin a melody: remember the B1 tick, load note 0 and start Timer W PWM on
; the watch clock with the compare-match A interrupt enabled.
start_score:
    mov.b #1, r0l
    mov.b r0l, @PLAYING
    mov.b @TICKS, r0l
    mov.b r0l, @SSTART
    sub.b r0l, r0l
    mov.b r0l, @NOTEIDX
    jsr @load_note
    bset #6, @CKSTPR2:8
    mov.l #TMRW, er5
    sub.b r0l, r0l
    mov.b r0l, @er5
    mov.b r0l, @TIERW
    mov.b #0xc2, r0l
    mov.b r0l, @TCRW
    mov.b #0x10, r0l
    mov.b r0l, @TIOR0
    mov.b #0x01, r0l
    mov.b r0l, @TIOR1
    mov.b @TSRW, r0l
    and.b #0xfe, r0l
    mov.b r0l, @TSRW
    sub.w r0, r0
    mov.w r0, @TCNT
    mov.b #1, r0l
    mov.b r0l, @TIERW
    mov.b #0x83, r0l
    mov.b r0l, @er5
    rts

notes:
    .byte NOTE_DATA

timerw_isr:
    push.w r0
    push.w r1
    push.l er3
    mov.b @TSRW, r0l
    and.b #0xfe, r0l
    mov.b r0l, @TSRW
    mov.w @R_PERIODS, r0
    inc.w #1, r0
    mov.w r0, @R_PERIODS
    mov.w @REMAIN, r0
    dec.w #1, r0
    mov.w r0, @REMAIN
    bne 9f
    mov.b @NOTEIDX, r0l
    inc.b r0l
    mov.b r0l, @NOTEIDX
    cmp.b #NOTE_COUNT, r0l
    bcc 2f
    jsr @load_note
    sub.w r0, r0
    mov.w r0, @TCNT
    bra 9f
2:  ; Melody finished: stop Timer W and tally the pass.
    mov.l #TMRW, er5
    sub.b r0l, r0l
    mov.b r0l, @er5
    mov.b r0l, @TIERW
    mov.b r0l, @PLAYING
    mov.w @R_SCORES, r0
    inc.w #1, r0
    mov.w r0, @R_SCORES
    mov.w @R_NOTES, r0
    add.w #NOTE_COUNT, r0
    mov.w r0, @R_NOTES
    mov.b #LAST_G, r0l
    mov.b r0l, @R_LASTPITCH
    mov.b @TICKS, r0l
    mov.b @SSTART, r1l
    sub.b r1l, r0l
    sub.b r0h, r0h
    mov.w @R_B1MIN, r1
    cmp.w r1, r0
    bcc 1f
    mov.w r0, @R_B1MIN
1:  mov.w @R_B1MAX, r1
    cmp.w r1, r0
    bls 9f
    mov.w r0, @R_B1MAX
9:  pop.l er3
    pop.w r1
    pop.w r0
    rte

tb1_isr:
    bclr #2, @IRR2:8
    push.w r0
    mov.b @TICKS, r0l
    inc.b r0l
    mov.b r0l, @TICKS
    pop.w r0
    rte

rtc_isr:
    push.w r0
    sub.b r0l, r0l
    mov.b r0l, @RTCFLG
    pop.w r0
    rte
"""


def melody(seed: int) -> list[tuple[int, int]]:
    rng = random.Random(f"buzzer:{seed}")
    return [(rng.randrange(0x40, 0x71), rng.randrange(6, 10)) for _ in range(NOTES)]


def build_guest(seed: int):
    notes = melody(seed)
    data = ", ".join(str(v) for g, d in notes for v in (g, d))
    body = (GUEST.replace("NOTE_DATA", data)
            .replace("NOTE_COUNT", str(NOTES))
            .replace("LAST_G", str(notes[-1][0])))
    handlers = {"tb1": "tb1_isr", "timerw": "timerw_isr"}
    for n in range(23, 31):
        handlers[["rtc_quarter", "rtc_half", "rtc_second", "rtc_minute", "rtc_hour",
                  "rtc_week", "rtc_day", "rtc_free"][n - 23]] = "rtc_isr"
    return program(body, handlers, listing=Listing(), seed=seed)


def workload(seed: int) -> Workload:
    image, _symbols = build_guest(seed)
    notes = melody(seed)
    score_clocks = sum((g + 1) * d for g, d in notes)
    periods = sum(d for _g, d in notes)
    b1 = score_clocks // B1_CLOCKS  # Timer B1 ticks a melody spans.
    period, setup = 2000, 31

    def expected(n: int) -> dict:
        ram = {"f7fc": "00000000"}
        ram[f"{RESULTS:04x}"] = (u16(n) + u16(NOTES * n) + u16(periods * n)
                                 + bytes([notes[-1][0], 0]).hex())
        return {"ram": ram}

    def witnesses(n: int) -> dict:
        # A melody spans b1 or b1+1 Timer B1 ticks depending on its phase; the
        # windows allow that and one tick of sampling. A Timer W rate wrong by a
        # factor relative to the watch clock lands far outside.
        return {"b1_span_shortest": (RESULTS + 8, 2, b1 - 1, b1 + 1),
                "b1_span_longest": (RESULTS + 10, 2, b1, b1 + 2)}

    paced = Paced(period, setup, (1, 3, 7, 15, 31, 63, 127, 255, 511, 1023), expected, witnesses,
                  units=lambda n: {"scores": n, "notes": NOTES * n})
    return Workload(
        name="buzzer",
        tier="use",
        summary="Buzzer-heavy use: a seeded melody played each pass on Timer W PWM over the "
                "watch clock, with the compare-match cadence and its Timer B1 span checked",
        blocks=("cpu", "power", "timer_b1", "timer_w", "interrupts"),
        image=image, seed=seed,
        observe=("ram",),
        evidence={
            "kind": "software_reasoned",
            "source": "lumirth/pw BeepEnableTimer, BeepSetPeriod, BeepAdvance, TimerWInterrupt, "
                      "BeepTick, ClockSleep; REJ09B0152-0300 §10 (Timer W PWM, compare match A "
                      "on the watch clock), §6 (Timer B1 watch-clock interrupt), Table 5.3 "
                      "(Timer W runs in sleep mode, halts in watch mode)",
            "question": "Does each melody fire one compare-match A interrupt per (GRA+1) watch "
                        "clocks, advance through its notes, and span the number of Timer B1 "
                        "ticks the watch-clock rate implies?",
        },
        **paced.fields(),
    )


def workloads(seed: int):
    yield workload(seed)
