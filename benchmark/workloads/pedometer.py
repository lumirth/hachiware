"""Carry: the firmware's 16 Hz motion tick with the panel off.

Each Timer B1 tick wakes the CPU from watch mode into subactive mode. The guest
wakes the BMA150 over the subclock-driven SSU, services the watchdog, makes a
direct transition to active mode, reads X/Y/Z, puts the sensor to sleep, runs a
hysteresis step detector and returns to watch mode. Every 64 samples (4 s) it
runs the firmware's 64-point fixed-point FFT on all three axes and records the
dominant bin, as the retail pedometer does before estimating cadence.

The input holds each tick's acceleration over the whole sampling window, with
edges midway between samples, and every 4 s batch begins and ends with two
neutral samples. A pocket is never still: every sample carries seeded noise of
a few counts on each axis. About one batch in three is walking at a seeded
cadence and the rest are at rest, as a carried device spends most of its time,
so no two ticks need repeat. Every batch's steps and dominant bin are stored
in an EEPROM ring. The build checks that step counts and dominant bins do not
change if a model reads the previous conversion or a sample one tick late, or
converts with a gain error of 10% or an offset of two counts; a seed whose
noise makes a batch sensitive to those details is redrawn for that batch.
"""

from __future__ import annotations

import random

from ..runtime import RESULTS, program
from ..witness import timed, window
from ..workload import Paced, Workload, observed_fields, u16
from cases.asm import Listing

SINE = [
    0, 201, 400, 595, 784, 965, 1138, 1299, 1448, 1583, 1703, 1806, 1892, 1960,
    2009, 2038, 2048, 2038, 2009, 1960, 1892, 1806, 1703, 1583, 1448, 1299, 1138,
    965, 784, 595, 400, 201, 0, -201, -400, -595, -784, -965, -1138, -1299, -1448,
    -1583, -1703, -1806, -1892, -1960, -2009, -2038, -2048, -2038, -2009, -1960,
    -1892, -1806, -1703, -1583, -1448, -1299, -1138, -965, -784, -595, -400, -201,
    0, 201, 400, 595, 784, 965, 1138, 1299, 1448, 1583, 1703, 1806, 1892, 1960,
    2009, 2038,
]
THRESHOLD = 16  # Step hysteresis in MSB counts (64 per g).
PEAK_MINIMUM = 256  # Accumulated |re|+|im| needed to report a dominant bin.
BATCH = 64
TICK_US = 62_500
EDGE_US = 35_000  # Value k holds from EDGE_US + k*TICK_US (see module notes).
HALF_PERIODS = (2, 3, 4, 5, 6, 8)  # Walking half-periods, in ticks, chosen per batch.
NOISE = 2  # Sample noise in MSB counts on each axis.
WALK_G = 0.5
WALKING_ONE_IN = 3  # Share of batches that are walking.

GUEST = r"""
TICKS = 0xf820
SEEN = 0xf821
IDX = 0xf822
STATE = 0xf823
BSTEPS = 0xf824
MISSED = 0xf825
NTICKS = 0xf826
QUARTERS = 0xf828
SECONDS = 0xf82a
SNAPQ = 0xf82c
SNAPS = 0xf82e
WITSUB = 0xf830
WITACT = 0xf832
TMPR = 0xf834
STEPTOT = 0xf836
BATCHES = 0xf838
MINUTES = 0xf83a
PHASE = 0xf83c
STAGESTEPS = 0xf83d
STAGE = 0xfc00
REAL = 0xf900
IMAG = 0xf980
ACC = 0xfa00
RINGX = 0xfa40
RINGY = 0xfa80
RINGZ = 0xfac0
RES = 0xf780

    jsr @wdt_start
    jsr @hw_setup
    jsr @tb1_init
    jsr @rtc_init
    jsr @accel_init
    jsr @lcd_init
    mov.l #lcd_sleep, er1
    mov.b #1, r2l
    jsr @lcd_cmds
    mov.l #0xf820, er1
    mov.w #0x1f0, r2
    sub.w r0, r0
1:  mov.w r0, @er1
    adds #2, er1
    dec.w #1, r2
    bne 1b
    andc #0x7f, ccr
main:
    jsr @sleep_watch_sub
    mov.b @TICKS, r0l
    mov.b @SEEN, r0h
    cmp.b r0l, r0h
    beq main:16
    mov.b r0l, @SEEN
    sub.b r0h, r0l
    dec.b r0l
    beq 1f
    mov.b @MISSED, r0l
    inc.b r0l
    mov.b r0l, @MISSED
1:  bclr #2, @IENR2:8
    bclr #7, @IENR1:8
    jsr @capture
    bset #7, @IENR1:8
    bset #2, @IENR2:8
    sub.l er1, er1
    mov.b @IDX, r1l
    mov.b @0xf819, r0l
    mov.b r0l, @(RINGX,er1)
    mov.b @0xf81d, r0l
    mov.b r0l, @(RINGZ,er1)
    mov.b @0xf81b, r0l
    mov.b r0l, @(RINGY,er1)
    cmp.b #THRESH, r0l
    bge 2f
    cmp.b #-THRESH, r0l
    bgt 4f
    mov.b #2, r0h
    mov.b r0h, @STATE
    bra 4f
2:  mov.b @STATE, r0h
    cmp.b #2, r0h
    bne 3f
    mov.b @BSTEPS, r0h
    inc.b r0h
    mov.b r0h, @BSTEPS
3:  mov.b #1, r0h
    mov.b r0h, @STATE
4:  mov.w @NTICKS, r0
    inc.w #1, r0
    mov.w r0, @NTICKS
    mov.b @IDX, r0l
    inc.b r0l
    mov.b r0l, @IDX
    cmp.b #33, r0l
    bne 5f
    jsr @mid_batch
5:  mov.b @IDX, r0l
    cmp.b #64, r0l
    bne 6f
    jsr @close_batch
6:  mov.b @PHASE, r0l
    beq main:16
    jsr @batch_step
    jmp @main

tb1_isr:
    bclr #2, @IRR2:8
    push.w r0
    mov.b @TICKS, r0l
    inc.b r0l
    mov.b r0l, @TICKS
    pop.w r0
    rte

rtc_quarter_isr:
    push.w r0
    mov.b @RTCFLG, r0l
    and.b #0xfe, r0l
    mov.b r0l, @RTCFLG
    mov.w @QUARTERS, r0
    inc.w #1, r0
    mov.w r0, @QUARTERS
    pop.w r0
    rte

rtc_second_isr:
    push.w r0
    mov.b @RTCFLG, r0l
    and.b #0xfb, r0l
    mov.b r0l, @RTCFLG
    mov.w @SECONDS, r0
    inc.w #1, r0
    mov.w r0, @SECONDS
    pop.w r0
    rte

rtc_minute_isr:
    push.w r0
    mov.b @RTCFLG, r0l
    and.b #0xf7, r0l
    mov.b r0l, @RTCFLG
    mov.w @MINUTES, r0
    inc.w #1, r0
    mov.w r0, @MINUTES
    pop.w r0
    rte

rtc_hour_isr:
    push.w r0
    mov.b @RTCFLG, r0l
    and.b #0xef, r0l
    mov.b r0l, @RTCFLG
    pop.w r0
    rte

; Halfway through a batch: snapshot the RTC counts, time a subactive loop
; with Timer B1's counter and a straight-line block with Timer W.
mid_batch:
    mov.w @QUARTERS, r0
    mov.w r0, @SNAPQ
    mov.w @SECONDS, r0
    mov.w r0, @SNAPS
    mov.b #0xaf, r0l
    mov.b r0l, @SYSCR1:8
    mov.b #0xeb, r0l
    mov.b r0l, @SYSCR2:8
    sleep
    mov.b @TCB1, r1l
    mov.w #SUBLOOP, r0
1:  dec.w #1, r0
    bne 1b
    mov.b @TCB1, r1h
    mov.b #0xa7, r0l
    mov.b r0l, @SYSCR1:8
    mov.b #0xeb, r0l
    mov.b r0l, @SYSCR2:8
    sleep
    sub.b r1l, r1h
    and.b #7, r1h
    mov.b r1h, @WITSUB
    push.l er4
    push.l er5
    push.l er6
WITNESS
    pop.l er6
    pop.l er5
    pop.l er4
    rts

; Close a batch: stage its samples and steps, and start a new batch. The
; three FFTs and the result latch run on the next ticks, one per tick, so no
; tick's work exceeds the tick period.
close_batch:
    mov.l #RINGX, er1
    mov.l #STAGE, er2
    mov.b #192, r3l
1:  mov.b @er1+, r0l
    mov.b r0l, @er2
    adds #1, er2
    dec.b r3l
    bne 1b
    mov.b @BSTEPS, r0l
    mov.b r0l, @STAGESTEPS
    sub.b r0l, r0l
    mov.b r0l, @IDX
    mov.b r0l, @BSTEPS
    mov.b #1, r0l
    mov.b r0l, @PHASE
    rts

batch_step:
    mov.b @PHASE, r0l
    inc.b r0l
    mov.b r0l, @PHASE
    cmp.b #2, r0l
    bne 2f
    mov.l #ACC, er1
    mov.b #32, r2l
    sub.w r0, r0
1:  mov.w r0, @er1
    adds #2, er1
    dec.b r2l
    bne 1b
    mov.l #STAGE, er1
    jmp @fft_axis
2:  cmp.b #3, r0l
    bne end_batch
    mov.l #STAGE + 64, er1
    jmp @fft_axis

end_batch:
    sub.b r0l, r0l
    mov.b r0l, @PHASE
    mov.l #STAGE + 128, er1
    jsr @fft_axis
    ; First strict maximum of bins 1..31, or 0 below PEAK_MINIMUM.
    mov.w #PEAKMIN - 1, r1
    sub.b r2l, r2l
    mov.b #1, r2h
    mov.l #ACC + 2, er3
2:  mov.w @er3+, r0
    cmp.w r1, r0
    bls 3f
    mov.w r0, r1
    mov.b r2h, r2l
3:  inc.b r2h
    cmp.b #32, r2h
    blo 2b
    mov.w @BATCHES, r0
    inc.w #1, r0
    mov.w r0, @BATCHES
    mov.w r0, @RES
    dec.w #1, r0
    and.w #15, r0
    extu.l er0
    mov.b r2l, @(RES + 0x10, er0)
    mov.b r2l, @RES + 5
    mov.b @STAGESTEPS, r0l
    mov.b r0l, @RES + 4
    sub.b r0h, r0h
    mov.w @STEPTOT, r1
    add.w r0, r1
    mov.w r1, @STEPTOT
    mov.w r1, @RES + 2
    mov.w @SNAPQ, r0
    mov.w r0, @RES + 6
    mov.w @SNAPS, r0
    mov.w r0, @RES + 8
    mov.w @NTICKS, r0
    mov.w r0, @RES + 10
    ; The latch runs two ticks after the batch closed.
    mov.b @MISSED, r0l
    mov.b r0l, @RES + 12
    mov.b @WITSUB, r0l
    mov.b r0l, @RES + 13
    mov.w @WITACT, r0
    mov.w r0, @RES + 14
PERSIST
    rts

; FftAccumulate: er1 points at 64 signed samples.
fft_axis:
    push.l er4
    push.l er5
    push.l er6
    sub.l er2, er2
    mov.b #64, r3l
1:  mov.b @er1+, r0l
    exts.w r0
    mov.w r0, @(REAL,er2)
    sub.w r0, r0
    mov.w r0, @(IMAG,er2)
    adds #2, er2
    dec.b r3l
    bne 1b
    ; Bit reversal: j ^= partner until partner <= j.
    sub.b r1l, r1l
    mov.b #1, r1h
2:  mov.b #32, r0h
3:  xor.b r0h, r1l
    cmp.b r1l, r0h
    bls 4f
    shlr.b r0h
    bra 3b
4:  cmp.b r1l, r1h
    bhs 5f
    sub.l er2, er2
    mov.b r1h, r2l
    add.w r2, r2
    sub.l er3, er3
    mov.b r1l, r3l
    add.w r3, r3
    mov.w @(REAL,er2), r0
    mov.w @(REAL,er3), e0
    mov.w e0, @(REAL,er2)
    mov.w r0, @(REAL,er3)
5:  inc.b r1h
    cmp.b #63, r1h
    blo 2b
    ; Six radix-2 stages with Q11 twiddles.
    mov.b #64, r5l
    mov.b #1, r4l
6:  mov.b r4l, r4h
    add.b r4h, r4h
    cmp.b #64, r4h
    bhi 9f:16
    shlr.b r5l
    sub.b r5h, r5h
    sub.b r6l, r6l
7:  sub.l er2, er2
    mov.b r6l, r2l
    add.w r2, r2
    mov.w @(SINE_TABLE,er2), e6
    mov.w @(SINE_TABLE + 32,er2), e5
    mov.b r5h, r6h
8:  sub.l er3, er3
    mov.b r6h, r3l
    sub.l er2, er2
    mov.b r3l, r2l
    add.b r4l, r2l
    add.w r2, r2
    add.w r3, r3
    mov.w @(REAL,er2), r0
    mulxs.w e5, er0
    mov.w @(IMAG,er2), r1
    mulxs.w e6, er1
    sub.l er1, er0
    shll.l er0
    shll.l er0
    shll.l er0
    shll.l er0
    shll.l er0
    mov.w e0, @TMPR
    ; (s32 >> 11) truncated to 16 bits: bits 26..11 land in e0 after << 5.
    mov.w @(IMAG,er2), r0
    mulxs.w e5, er0
    mov.w @(REAL,er2), r1
    mulxs.w e6, er1
    add.l er1, er0
    shll.l er0
    shll.l er0
    shll.l er0
    shll.l er0
    shll.l er0
    mov.w e0, r0
    mov.w @(IMAG,er3), r1
    sub.w r0, r1
    mov.w r1, @(IMAG,er2)
    mov.w @(IMAG,er3), r1
    add.w r0, r1
    mov.w r1, @(IMAG,er3)
    mov.w @TMPR, r0
    mov.w @(REAL,er3), r1
    sub.w r0, r1
    mov.w r1, @(REAL,er2)
    mov.w @(REAL,er3), r1
    add.w r0, r1
    mov.w r1, @(REAL,er3)
    add.b r4h, r6h
    cmp.b #64, r6h
    blo 8b:16
    inc.b r5h
    add.b r5l, r6l
    cmp.b r4l, r5h
    blo 7b:16
    mov.b r4h, r4l
    bra 6b:16
    ; Accumulate |re| + |im| of bins 0..31.
9:  sub.l er2, er2
    mov.b #32, r3l
10: mov.w @(REAL,er2), r0
    bpl 11f
    neg.w r0
11: mov.w @(IMAG,er2), r1
    bpl 12f
    neg.w r1
12: add.w r1, r0
    mov.w @(ACC,er2), r1
    add.w r0, r1
    mov.w r1, @(ACC,er2)
    adds #2, er2
    dec.b r3l
    bne 10b
    pop.l er6
    pop.l er5
    pop.l er4
    rts

    .align 2
SINE_TABLE:
    .word SINEDATA
"""

PERSIST = r"""
    ; Persist the batch record {batch, steps, bin} at 0x2000 + 4 * (batch mod 64).
    mov.w @RES, r0
    mov.w r0, @0xf840
    mov.b @RES + 4, r0l
    mov.b r0l, @0xf842
    mov.b @RES + 5, r0l
    mov.b r0l, @0xf843
    mov.w @RES, r1
    dec.w #1, r1
    and.w #63, r1
    shll.w r1
    shll.w r1
    add.w #0x2000, r1
    mov.l #0xf840, er2
    mov.w #4, r3
    jsr @eep_write
"""

SUBLOOP = 100


def guest(seed: int) -> tuple[bytes, dict, tuple[int, int]]:
    body = GUEST.replace("SINEDATA", ", ".join(str(v) for v in SINE))
    body = body.replace("THRESH", str(THRESHOLD)).replace("PEAKMIN", str(PEAK_MINIMUM))
    body = body.replace("SUBLOOP", str(SUBLOOP))
    body = body.replace("WITNESS", timed("wit", seed ^ 0x5EED, 160, 0xF832))
    body = body.replace("PERSIST", PERSIST)
    listing = Listing()
    image, symbols = program(
        body,
        {
            "tb1": "tb1_isr", "rtc_quarter": "rtc_quarter_isr",
            "rtc_second": "rtc_second_isr", "rtc_minute": "rtc_minute_isr",
            "rtc_hour": "rtc_hour_isr",
        },
        listing=listing,
        seed=seed,
    )
    return image, symbols, window(listing, symbols, "wit")


# ----------------------------------------------------------------- model


def s16(value: int) -> int:
    value &= 0xFFFF
    return value - 0x10000 if value & 0x8000 else value


def fft_accumulate(samples: list[int], acc: list[int]) -> None:
    """lumirth/pw FftAccumulate with 16-bit storage and arithmetic shifts."""
    real = [s16(v) for v in samples]
    imag = [0] * 64
    j = 0
    for i in range(1, 63):
        partner = 32
        while True:
            j ^= partner
            if not partner > j:
                break
            partner >>= 1
        if i < j:
            real[i], real[j] = real[j], real[i]
    phase, half = 64, 1
    while half * 2 <= 64:
        span = half * 2
        phase >>= 1
        twiddle = 0
        for j in range(half):
            cos, sin = SINE[twiddle + 16], SINE[twiddle]
            for i in range(j, 64, span):
                p = i + half
                rr = s16((real[p] * cos - imag[p] * sin) >> 11)
                ri = s16((imag[p] * cos + real[p] * sin) >> 11)
                real[p], imag[p] = s16(real[i] - rr), s16(imag[i] - ri)
                real[i], imag[i] = s16(real[i] + rr), s16(imag[i] + ri)
            twiddle += phase
        half = span
    for b in range(32):
        acc[b] = (acc[b] + ((abs(real[b]) + abs(imag[b])) & 0xFFFF)) & 0xFFFF


def dominant(xs, ys, zs) -> int:
    acc = [0] * 32
    for axis in (xs, ys, zs):
        fft_accumulate(axis, acc)
    best, peak = PEAK_MINIMUM - 1, 0
    for b in range(1, 32):
        if acc[b] > best:
            best, peak = acc[b], b
    return peak


def counts(value: int, gain: float = 1.0, offset: int = 0) -> int:
    """MSB counts (64 per g) of a level given in MSB counts, with conversion errors."""
    return max(-128, min(127, round(value * gain) + offset))


def detect(ys: list[int], state: int) -> tuple[int, int]:
    steps = 0
    for y in ys:
        if y >= THRESHOLD:
            if state == 2:
                steps += 1
            state = 1
        elif y <= -THRESHOLD:
            state = 2
    return steps, state


# Conversion variants a correct emulator may legitimately differ by: a sample
# one tick late, a gain error and an offset.
VARIANTS = ((1, 1.0, 0), (0, 0.9, 2), (0, 1.1, -2), (1, 1.1, 2), (0, 0.9, -2))


class Signal:
    """Seeded per-tick acceleration in MSB counts and the expected batch results."""

    def __init__(self, seed: int):
        self.seed = seed
        self.ticks: list[tuple[int, int, int]] = []
        self.results: list[tuple[int, int]] = []
        self.state = 0

    def batch(self, b: int, attempt: int) -> list[tuple[int, int, int]]:
        # Whether a batch is walking does not depend on redraws.
        walking = random.Random(f"carry-mode:{self.seed}:{b}").randrange(WALKING_ONE_IN) == 0
        rng = random.Random(f"carry:{self.seed}:{b}:{attempt}")
        half = rng.choice(HALF_PERIODS) if walking else 0
        phase = rng.randrange(2 * half) if half else 0
        values = []
        for t in range(BATCH):
            nx, ny, nz = (rng.randint(-NOISE, NOISE) for _ in range(3))
            if t < 2 or t >= BATCH - 2:
                values.append((0, 0, 64))  # Neutral samples bound every batch.
                continue
            y = 0
            if half:
                y = -32 if ((t - 2 + phase) // half) % 2 == 0 else 32
            values.append((nx, y + ny, 64 + nz))
        return values

    def results_for(self, ticks, b, shift, gain, offset, state):
        lo = b * BATCH - shift
        window = [ticks[i] if 0 <= i < len(ticks) else (0, 0, 64) for i in range(lo, lo + BATCH)]
        xs = [counts(x, gain, offset) for x, _, _ in window]
        ys = [counts(y, gain, offset) for _, y, _ in window]
        zs = [counts(z, gain, offset) for _, _, z in window]
        steps, state = detect(ys, state)
        return (steps, dominant(xs, ys, zs)), state

    def extend(self, batches: int) -> list[tuple[int, int]]:
        """Results of the first ``batches`` batches, redrawing sensitive batches."""
        while len(self.results) < batches:
            b = len(self.results)
            for attempt in range(64):
                ticks = self.ticks + self.batch(b, attempt)
                nominal, state = self.results_for(ticks, b, 0, 1.0, 0, self.state)
                # A variant reads one batch's window under its own conversion; the
                # detector state at a batch boundary is neutral by construction.
                if all(self.results_for(ticks, b, *v, self.state)[0] == nominal
                       for v in VARIANTS):
                    break
            else:
                raise ValueError(f"no robust batch {b} for seed {self.seed}")
            self.ticks, self.state = ticks, state
            self.results.append(nominal)
        return self.results[:batches]

    def timeline(self, milliseconds: int) -> str:
        ticks = milliseconds * 1000 // TICK_US + 2
        self.extend(ticks // BATCH + 1)
        rows = []
        for k in range(ticks):
            x, y, z = self.ticks[k]
            at = 0 if k == 0 else EDGE_US + k * TICK_US
            # Bin centres: (4m + 2) ten-bit counts of 3906.25 micro-g.
            rows.append(f"{at},accel," + ",".join(str(v * 15625 + 7812) for v in (x, y, z)))
        return "\n".join(rows) + "\n"


def build(seed: int) -> Workload:
    image, symbols, (low, high) = guest(seed)
    signal = Signal(seed)
    period, setup = 4000, 31

    def expected(n: int) -> dict:
        # Horizon = setup + n*4000 + 2000 ms: n batches are complete.
        results = signal.extend(n)
        h = setup + n * period + period // 2
        ram = {}
        if n:
            steps, peak = results[-1]
            total = sum(s for s, _ in results)
            history = bytearray(16)
            for b, (_s, p) in enumerate(results):
                history[b % 16] = p
            ram[f"{RESULTS:04x}"] = (
                u16(n) + u16(total) + bytes([steps, peak]).hex()
                + u16(8 + 16 * (n - 1)) + u16(2 + 4 * (n - 1)) + u16(64 * n + 2) + "00"
            )
            ram[f"{RESULTS + 16:04x}"] = history.hex()
        ram["f7fc"] = "00000000"
        # Minutes counted by the RTC minute interrupt.
        ram["f83a"] = u16(h // 60000)
        out = {"ram": ram}
        if n:
            eeprom = {}
            for b, (s, p) in enumerate(results[-64:], max(1, n - 63)):
                address = 0x2000 + 4 * ((b - 1) % 64)
                eeprom[address] = u16(b) + bytes([s, p]).hex()
            out["eeprom"] = {f"{a:04x}": v for a, v in sorted(eeprom.items())}
        return out

    def witnesses(n: int) -> dict:
        return {
            "subactive_tb1_counts": (RESULTS + 13, 1, 2, 3),
            "active_timer_w": (RESULTS + 14, 2, low, high),
        } if n else {}

    paced = Paced(period, setup, (1, 3, 7, 15, 31, 63, 127, 255, 511, 1023), expected,
                  witnesses, lambda n: {"ticks": 32 + 64 * n, "batches": n})
    return Workload(
        name="carry",
        tier="use",
        summary=("Carried all day: 16 Hz watch-mode motion tick on a noisy sensor, rest "
                 "and walking batches, step detector, FFT cadence per 4 s batch, batch "
                 "records in EEPROM, panel in power save, RTC running"),
        blocks=("cpu", "power", "timer_b1", "rtc", "watchdog", "ssu", "accelerometer",
                "interrupts", "eeprom"),
        image=image,
        observe=observed_fields(expected(1)),
        timeline=signal.timeline,
        inputs=("accel",),
        seed=seed,
        evidence={
            "kind": "software_reasoned",
            "source": "lumirth/pw MainTick, CaptureSample, ClockSleep, AccelRead, FftAccumulate, "
            "EepromWrite; REJ09B0152-0300 §5 (Table 5.2), §11, §12, §9 (Timer B1), "
            "Table A.4; BMA150 data sheet (MSB register, 2 g range)",
            "question": "Does the 16 Hz watch/subactive/active motion tick deliver every "
            "sample, interrupt and stored result on time, with subactive code at phiW "
            "and active code at the documented state counts?",
        },
        **paced.fields(),
    )


def workloads(seed: int):
    yield build(seed)
