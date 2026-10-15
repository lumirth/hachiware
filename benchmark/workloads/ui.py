"""Screen-on workloads: the animated home screen and button-driven menus.

Both wake from watch mode into active high-speed mode on each 16 Hz Timer B1
tick, as ClockSleep(LOW_POWER) does while the panel is on, and redraw through
the firmware's display path: DisplayClear of the drawing bank, EepromRead of
artwork into RAM, DisplayBlit, then DisplayToggleBank to show the new bank.
Artwork lives in the EEPROM image. Expected panel RAM follows from the drawing
order; columns 96..127 are never written and are not checked.
"""

from __future__ import annotations

import random

from cases.asm import Listing

from ..runtime import RESULTS, program
from ..workload import Paced, Workload, observed_fields, u16

SPRITE = 0x4000  # Two 32x24 frames, 192 bytes each.
DIGITS = 0x4200  # Ten 8x8 glyphs, 16 bytes each.
ICONS = 0x4400  # Six 16x16 icons, 64 bytes each.
ARROW = 0x4600  # 8x8 cursor.
MARK = 0x4610  # 8x8 check mark.
TICK_US = 62_500
CLEAR_BYTES = 8 * (3 + 192)


def artwork(seed: int) -> bytes:
    rng = random.Random(f"artwork:{seed}")
    image = bytearray([0xFF]) * 65536
    for start, size in ((SPRITE, 384), (DIGITS, 160), (ICONS, 384), (ARROW, 16), (MARK, 16)):
        image[start:start + size] = bytes(rng.randrange(256) for _ in range(size))
    return bytes(image)


class Panel:
    """NT7508 display RAM as written by the guest's drawing routines."""

    def __init__(self):
        self.ram = bytearray(4096)

    def clear(self, bank: int):
        for page in range(8):
            base = (bank * 8 + page) * 256
            self.ram[base:base + 192] = bytes(192)

    def blit(self, bank: int, data: bytes, x: int, page: int, width: int, pages: int):
        i = 0
        for p in range(page, page + pages):
            base = (bank * 8 + p) * 256 + 2 * x
            self.ram[base:base + 2 * width] = data[i:i + 2 * width]
            i += 2 * width

    def expected(self) -> dict:
        return {f"{row * 256:04x}": self.ram[row * 256:row * 256 + 192].hex()
                for row in range(16)}


COMMON = r"""
TICKS = 0xf820
SEEN = 0xf821
FRAMES = 0xf822
NTICKS = 0xf824
WITLCD = 0xf826
CURSOR = 0xf828
CHECKED = 0xf829
PREV = 0xf82a
BEEPS = 0xf82c
PERIODS = 0xf82e
REMAIN = 0xf830
PRESSES = 0xf832
COL = 0xf834
BUF = 0xfa00
RES = 0xf780

    jsr @wdt_start
    jsr @hw_setup
    jsr @tb1_init
    jsr @rtc_init
    jsr @accel_init
    jsr @lcd_init
    mov.l #0xf820, er1
    mov.w #0x40, r2
    sub.w r0, r0
1:  mov.w r0, @er1
    adds #2, er1
    dec.w #1, r2
    bne 1b
INIT
    andc #0x7f, ccr
main:
SLEEP
    mov.b @TICKS, r0l
    mov.b @SEEN, r0h
    cmp.b r0l, r0h
    beq main
    mov.b r0l, @SEEN
    jsr @wdt_kick
    jsr @sample
    mov.w @NTICKS, r0
    inc.w #1, r0
    mov.w r0, @NTICKS
TICK
    jmp @main

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

; Wake the sensor, read X/Y/Z on the main-clock SSU and put it back to sleep.
sample:
    mov.w #0x0a00, r0
    jsr @accel_write
    mov.b #0x02, r0l
    mov.l #0xf818, er2
    mov.b #6, r3l
    jsr @accel_read
    mov.w #0x0a01, r0
    jmp @accel_write

; Load r3 bytes of artwork at EEPROM r1 into BUF and blit them at column
; r4l, page r4h, width r5l, r5h pages.
draw:
    mov.l #BUF, er2
    jsr @eep_read
    mov.l #BUF, er1
    mov.w r4, r2
    mov.w r5, r3
    jmp @lcd_blit
"""

WATCH_TICK = r"""
    mov.w @NTICKS, r0
    btst #0, r0l
    beq 9f
    jsr @frame
9:  mov.w @NTICKS, r0
    and.w #31, r0
    bne 8f
    mov.w @FRAMES, r0
    mov.w r0, @RES
    mov.w @NTICKS, r0
    mov.w r0, @RES + 2
    mov.w @WITLCD, r0
    mov.w r0, @RES + 4
8:
"""

WATCH_BODY = r"""
; One animation frame: clear the drawing bank (timed with Timer W at phi/8),
; sprite frame FRAMES mod 2, five-digit frame number, then show the bank.
frame:
    bset #6, @CKSTPR2:8
    mov.l #TMRW, er5
    bclr #7, @er5
    mov.b #0x30, r0l
    mov.b r0l, @TCRW
    sub.w r0, r0
    mov.w r0, @TCNT
    bset #7, @er5
    jsr @lcd_clear
    mov.l #TMRW, er5
    bclr #7, @er5
    mov.w @TCNT, r0
    mov.w r0, @WITLCD
    mov.w @FRAMES, r0
    and.w #1, r0
    mov.w #192, r1
    mulxu.b r0l, r1
    add.w #SPRITE, r1
    mov.w #192, r3
    mov.w #0x0220, r4
    mov.w #0x0320, r5
    jsr @draw
    ; Digits, most significant first, from repeated division by 10.
    mov.w @FRAMES, r0
    extu.l er0
    mov.l #0xf840, er6
    mov.w #5, e5
1:  mov.w #10, r1
    divxu.w r1, er0
    mov.w e0, r2
    mov.b r2l, @-er6
    extu.l er0
    dec.w #1, e5
    bne 1b
    mov.b #24, r0l
    mov.b r0l, @COL
2:  mov.b @er6+, r1l
    sub.b r1h, r1h
    shll.w r1
    shll.w r1
    shll.w r1
    shll.w r1
    add.w #DIGITS, r1
    mov.w #16, r3
    mov.b @COL, r4l
    mov.b #6, r4h
    mov.w #0x0108, r5
    push.l er6
    jsr @draw
    pop.l er6
    mov.b @COL, r0l
    add.b #8, r0l
    mov.b r0l, @COL
    cmp.b #64, r0l
    bne 2b
    jsr @lcd_toggle
    mov.w @FRAMES, r0
    inc.w #1, r0
    mov.w r0, @FRAMES
    rts
"""

MENU_INIT = r"""
    jsr @redraw
"""

MENU_TICK = r"""
    ; InputScan: PDRB bit 0 centre, bit 2 left, bit 4 right; act on new presses.
    mov.b @PDRB:8, r0l
    and.b #0x15, r0l
    mov.b @PREV, r0h
    mov.b r0l, @PREV
    not.b r0h
    and.b r0h, r0l
    beq 9f
    mov.w @PRESSES, r1
    inc.w #1, r1
    mov.w r1, @PRESSES
    mov.b @CURSOR, r1l
    btst #4, r0l
    beq 1f
    inc.b r1l
    cmp.b #6, r1l
    bne 1f
    sub.b r1l, r1l
1:  btst #2, r0l
    beq 2f
    add.b #5, r1l
    cmp.b #6, r1l
    blo 2f
    add.b #-6, r1l
2:  mov.b r1l, @CURSOR
    btst #0, r0l
    beq 3f
    mov.b @CHECKED, r2l
    sub.l er3, er3
    mov.b r1l, r3l
    mov.b @(MASKS,er3), r2h
    xor.b r2h, r2l
    mov.b r2l, @CHECKED
3:  jsr @beep
    jsr @redraw
9:  mov.w @NTICKS, r0
    and.w #31, r0
    bne 8f
    mov.w @FRAMES, r0
    mov.w r0, @RES
    mov.w @NTICKS, r0
    mov.w r0, @RES + 2
    mov.w @PRESSES, r0
    mov.w r0, @RES + 4
    mov.w @BEEPS, r0
    mov.w r0, @RES + 6
    mov.w @PERIODS, r0
    mov.w r0, @RES + 8
    mov.b @CURSOR, r0l
    mov.b r0l, @RES + 10
    mov.b @CHECKED, r0l
    mov.b r0l, @RES + 11
8:
"""

MENU_BODY = r"""
; Redraw the menu: six icons, check marks above selected items and the cursor.
redraw:
    jsr @lcd_clear
    sub.b r6l, r6l
1:  mov.b r6l, r1l
    sub.b r1h, r1h
    shll.w r1
    shll.w r1
    shll.w r1
    shll.w r1
    shll.w r1
    shll.w r1
    add.w #ICONS, r1
    mov.w #64, r3
    mov.b r6l, r4l
    shll.b r4l
    shll.b r4l
    shll.b r4l
    shll.b r4l
    mov.b #2, r4h
    mov.w #0x0210, r5
    push.l er6
    jsr @draw
    pop.l er6
    mov.b @CHECKED, r0l
    sub.l er3, er3
    mov.b r6l, r3l
    mov.b @(MASKS,er3), r0h
    and.b r0h, r0l
    beq 2f
    mov.w #MARK, r1
    mov.w #16, r3
    mov.b r6l, r4l
    shll.b r4l
    shll.b r4l
    shll.b r4l
    shll.b r4l
    add.b #4, r4l
    mov.b #0, r4h
    mov.w #0x0108, r5
    push.l er6
    jsr @draw
    pop.l er6
2:  inc.b r6l
    cmp.b #6, r6l
    bne 1b
    mov.w #ARROW, r1
    mov.w #16, r3
    mov.b @CURSOR, r4l
    shll.b r4l
    shll.b r4l
    shll.b r4l
    shll.b r4l
    add.b #4, r4l
    mov.b #5, r4h
    mov.w #0x0108, r5
    jsr @draw
    jsr @lcd_toggle
    mov.w @FRAMES, r0
    inc.w #1, r0
    mov.w r0, @FRAMES
    rts

; Key click: Timer W counts phiW, clears on GRA and drives PWM on FTIOB/C
; (BeepEnableTimer, BeepSetPeriod); the compare-A interrupt counts periods
; and stops the timer after BEEP_PERIODS.
beep:
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
    mov.w #BEEP_GRA, r0
    mov.w r0, @GRA
    shlr.w r0
    mov.w r0, @GRB
    mov.w r0, @GRC
    mov.b @TSRW, r0l
    and.b #0xfe, r0l
    mov.b r0l, @TSRW
    mov.w #BEEP_PERIODS, r0
    mov.w r0, @REMAIN
    sub.w r0, r0
    mov.w r0, @TCNT
    mov.b #1, r0l
    mov.b r0l, @TIERW
    mov.b #0x83, r0l
    mov.b r0l, @er5
    mov.w @BEEPS, r0
    inc.w #1, r0
    mov.w r0, @BEEPS
    rts

MASKS:
    .byte 1, 2, 4, 8, 16, 32, 64, 128

timerw_isr:
    push.w r0
    mov.b @TSRW, r0l
    and.b #0xfe, r0l
    mov.b r0l, @TSRW
    mov.w @PERIODS, r0
    inc.w #1, r0
    mov.w r0, @PERIODS
    mov.w @REMAIN, r0
    dec.w #1, r0
    mov.w r0, @REMAIN
    bne 1f
    sub.b r0l, r0l
    mov.b r0l, @TIERW
    mov.b r0l, @TMRW
1:  pop.w r0
    rte
"""

BEEP_GRA = 15  # 32768 / 16 = 2048 Hz.
BEEP_PERIODS = 96  # 46.9 ms.


def build_guest(kind: str, seed: int):
    if kind == "watch":
        body = COMMON.replace("INIT", "").replace("TICK\n", WATCH_TICK) + WATCH_BODY
        body = body.replace("SLEEP", "    jsr @sleep_watch_active")
        handlers = {"tb1": "tb1_isr"}
    else:
        body = COMMON.replace("INIT", MENU_INIT).replace("TICK\n", MENU_TICK) + MENU_BODY
        # Timer W halts in watch mode (Table 5.3), so a click sleeps in sleep mode.
        body = body.replace("SLEEP", """    mov.w @REMAIN, r0
    beq 1f
    jsr @sleep_idle
    bra 2f
1:  jsr @sleep_watch_active
2:""")
        body = body.replace("BEEP_GRA", str(BEEP_GRA)).replace("BEEP_PERIODS", str(BEEP_PERIODS))
        handlers = {"tb1": "tb1_isr", "timerw": "timerw_isr"}
    for n in range(23, 31):
        handlers[["rtc_quarter", "rtc_half", "rtc_second", "rtc_minute", "rtc_hour",
                  "rtc_week", "rtc_day", "rtc_free"][n - 23]] = "rtc_isr"
    for name, value in (("SPRITE", SPRITE), ("DIGITS", DIGITS), ("ICONS", ICONS),
                        ("ARROW", ARROW), ("MARK", MARK)):
        body = body.replace(f"#{name}", f"#{value:#x}")
    listing = Listing()
    return program(body, handlers, listing=listing, seed=seed)


def watch_face(seed: int) -> Workload:
    image, _symbols = build_guest("watch", seed)
    eeprom = artwork(seed)
    period, setup = 2000, 31

    def frames_by(n: int) -> int:
        # Horizon offset 31 + 2000n + 1000 ms: ticks 0 .. 32n+15 have run and
        # frames are drawn on even ticks, so frames 0 .. 16n+7 exist.
        return 16 * n + 8

    def expected(n: int) -> dict:
        panel = Panel()
        count = frames_by(n)
        # Only the last frame drawn into each bank survives.
        for k in range(max(0, count - 2), count):
            bank = k % 2
            panel.clear(bank)
            panel.blit(bank, eeprom[SPRITE + 192 * (k % 2):][:192], 32, 2, 32, 3)
            for i, digit in enumerate(f"{k:05d}"):
                d = int(digit)
                panel.blit(bank, eeprom[DIGITS + 16 * d:][:16], 24 + 8 * i, 6, 8, 1)
        ram = {"f7fc": "00000000"}
        if n:
            # Latched at tick 32n (count after the increment), whose frame runs after.
            ram[f"{RESULTS:04x}"] = u16(16 * n) + u16(32 * n)
        return {
            "lcd": panel.expected(),
            "display_start": 64 * ((count - 1) % 2),
            "ram": ram,
        }

    def witnesses(n: int) -> dict:
        # phi/8 counts; each byte needs 8 SSU clocks of phi/4. The upper bound
        # allows 30% CPU refill latency and 600 states of addressing per page.
        low = CLEAR_BYTES * 32 // 8
        high = (CLEAR_BYTES * 32 * 13 // 10 + 8 * 600) // 8
        return {"lcd_clear_phi8": (RESULTS + 4, 2, low, high)} if n else {}

    paced = Paced(period, setup, (1, 3, 7, 15, 31, 63, 127, 255, 511), expected, witnesses,
                  lambda n: {"frames": frames_by(n)})
    return Workload(
        name="watch-face",
        tier="use",
        summary="Screen on: 8 fps animated home screen with seeded artwork read from EEPROM",
        blocks=("cpu", "power", "timer_b1", "timer_w", "ssu", "lcd", "eeprom",
                "accelerometer", "interrupts"),
        image=image, eeprom=eeprom, seed=seed,
        observe=observed_fields(expected(1)),
        evidence={
            "kind": "software_reasoned",
            "source": "lumirth/pw DisplayInit, DisplayClear, DisplayBlit, DisplayToggleBank, "
            "EepromRead, ClockSleep(LOW_POWER); NT7508 V1.0 command set; "
            "REJ09B0152-0300 §15 (SSU transfer clock)",
            "question": "Does the animated home screen leave the panel RAM, visible bank and "
            "SSU transfer time the firmware's drawing order and phi/4 serial clock imply?",
        },
        **paced.fields(),
    )


# Menu presses: offsets within the 2 s pass in ms. With the 31 ms setup offset
# each starts midway between ticks (62.5 m - 4 ms) and lasts 200 ms, so exactly
# one scan sees each new press. The seed chooses each press's button.
PRESS_OFFSETS = (308, 684, 1308, 1684)


def presses(seed: int, count: int) -> list[str]:
    rng = random.Random(f"menu:{seed}")
    return [rng.choice("LCRR") for _ in range(count)]


def menu_timeline(seed: int, milliseconds: int) -> str:
    rows = []
    passes = milliseconds // 2000 + 1
    buttons = presses(seed, 4 * passes)
    for p in range(passes):
        for i, offset in enumerate(PRESS_OFFSETS):
            start = 2000 * p + offset + 31
            if start > milliseconds:
                continue
            bits = {"L": "1,0,0", "C": "0,1,0", "R": "0,0,1"}[buttons[4 * p + i]]
            rows.append(f"{start * 1000},buttons,{bits}")
            rows.append(f"{(start + 200) * 1000},buttons,0,0,0")
    return "\n".join(rows) + "\n"


def menu(seed: int) -> Workload:
    image, _symbols = build_guest("menu", seed)
    eeprom = artwork(seed)
    period, setup = 2000, 31

    def state(count: int):
        cursor, checked = 0, 0
        frames = [(cursor, checked)]
        for button in presses(seed, count):
            if button == "R":
                cursor = (cursor + 1) % 6
            elif button == "L":
                cursor = (cursor + 5) % 6
            else:
                checked ^= 1 << cursor
            frames.append((cursor, checked))
        return frames

    def draw(panel, bank, cursor, checked):
        panel.clear(bank)
        for i in range(6):
            panel.blit(bank, eeprom[ICONS + 64 * i:][:64], 16 * i, 2, 16, 2)
            if checked >> i & 1:
                panel.blit(bank, eeprom[MARK:][:16], 16 * i + 4, 0, 8, 1)
        panel.blit(bank, eeprom[ARROW:][:16], 16 * cursor + 4, 5, 8, 1)

    def expected(n: int) -> dict:
        # By the horizon (pass offset 1031 ms) the first two presses of pass n are done.
        frames = state(4 * n + 2)
        panel = Panel()
        for k in range(max(0, len(frames) - 2), len(frames)):
            draw(panel, k % 2, *frames[k])
        ram = {"f7fc": "00000000"}
        if n:
            cursor, checked = frames[4 * n]
            ram[f"{RESULTS:04x}"] = (u16(4 * n + 1) + u16(32 * n) + u16(4 * n) + u16(4 * n)
                                     + u16(4 * n * BEEP_PERIODS)
                                     + bytes([cursor, checked]).hex())
        return {
            "lcd": panel.expected(),
            "display_start": 64 * ((len(frames) - 1) % 2),
            "ram": ram,
        }

    paced = Paced(period, setup, (1, 3, 7, 15, 31, 63, 127, 255, 511), expected,
                  units=lambda n: {"presses": 4 * n + 2})
    return Workload(
        name="menu",
        tier="use",
        summary="Screen on: seeded button presses drive a menu with key clicks on Timer W "
                "and full redraws",
        blocks=("cpu", "power", "timer_b1", "timer_w", "ssu", "lcd", "eeprom", "ports",
                "interrupts"),
        image=image, eeprom=eeprom, seed=seed,
        observe=observed_fields(expected(1)),
        timeline=lambda ms: menu_timeline(seed, ms),
        inputs=("buttons",),
        evidence={
            "kind": "software_reasoned",
            "source": "lumirth/pw InputScan, BeepEnableTimer, BeepSetPeriod, TimerWInterrupt, "
            "DisplayBlit; REJ09B0152-0300 §10 (Timer W PWM, compare match A)",
            "question": "Does each button press reach the scan, produce a key click of the "
            "programmed number of phiW periods and redraw the menu exactly once?",
        },
        **paced.fields(),
    )


def workloads(seed: int):
    yield watch_face(seed)
    yield menu(seed)
