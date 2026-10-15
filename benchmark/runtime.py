"""Assembly runtime shared by benchmark guests.

The routines follow the register sequences of the retail firmware drivers in
lumirth/pw (HardwareSetup, WatchdogStart/Service, TimerB1Init, ClockSleep,
CaptureSample, AccelRead/Write/Init, EepromRead/Write, Display*), rewritten as
original assembly. Calling convention: arguments in r0..r3/er1..er3, er0..er3
clobbered, er4..er6 preserved.

RAM layout: 0xF780..0xF7BF holds results that guests latch at pass
boundaries, 0xF7FB records the last unexpected vector, 0xF7FC counts
unexpected interrupts and 0xF7FE counts SSU overruns. Work variables start at 0xF800; the stack starts at 0xFF80.
"""

from __future__ import annotations

from cases.asm import Listing, assemble

PHI = 3_686_400
PHI_W = 32_768
TICK_STATES = PHI // 16  # Timer B1 at phiW/256 reloading 0xF8: 16 Hz.
TICK_SUBCLOCKS = PHI_W // 16

RESULTS = 0xF780
UNEXPECTED = 0xF7FC
OVERRUNS = 0xF7FE
WORK = 0xF800

EQUATES = """
SYSCR1 = 0xfff0
SYSCR2 = 0xfff1
IEGR = 0xfff2
IENR1 = 0xfff3
IENR2 = 0xfff4
IRR1 = 0xfff6
IRR2 = 0xfff7
CKSTPR1 = 0xfffa
CKSTPR2 = 0xfffb
TMB1 = 0xf0d0
TCB1 = 0xf0d1
SSCRH = 0xf0e0
SSCRL = 0xf0e1
SSMR = 0xf0e2
SSER = 0xf0e3
SSSR = 0xf0e4
SSRDR = 0xf0e9
SSTDR = 0xf0eb
TMRW = 0xf0f0
TCRW = 0xf0f1
TIERW = 0xf0f2
TSRW = 0xf0f3
TIOR0 = 0xf0f4
TIOR1 = 0xf0f5
TCNT = 0xf0f6
GRA = 0xf0f8
GRB = 0xf0fa
GRC = 0xf0fc
GRD = 0xf0fe
RTCFLG = 0xf067
RSECDR = 0xf068
RTCCR1 = 0xf06c
RTCCR2 = 0xf06d
RTCCSR = 0xf06f
PUCR9 = 0xf087
SPCR = 0xff91
SMR3 = 0xff98
BRR3 = 0xff99
SCR3 = 0xff9a
TDR3 = 0xff9b
SSR3 = 0xff9c
RDR3 = 0xff9d
SEMR = 0xffa6
IRCR = 0xffa7
TMWD = 0xffb0
TCSRWD1 = 0xffb1
TCSRWD2 = 0xffb2
TCWD = 0xffb3
PMR1 = 0xffc0
PMRB = 0xffca
PDR1 = 0xffd4
PDR8 = 0xffdb
PDR9 = 0xffdc
PDRB = 0xffde
PCR1 = 0xffe4
PCR8 = 0xffeb
PCR9 = 0xffec
UNEXPECTED = 0xf7fc
OVERRUNS = 0xf7fe
BANK = 0xf800
"""

# Vector numbers from REJ09B0152-0300 Table 4.1.
VECTORS = {
    "nmi": 7, "trapa0": 8, "trapa1": 9, "trapa2": 10, "trapa3": 11, "sleep": 12,
    "direct": 13, "irq0": 16, "irq1": 17, "irqaec": 18, "comp0": 21, "comp1": 22,
    "rtc_quarter": 23, "rtc_half": 24, "rtc_second": 25, "rtc_minute": 26,
    "rtc_hour": 27, "rtc_week": 28, "rtc_day": 29, "rtc_free": 30, "wdt": 31,
    "aec": 32, "tb1": 33, "ssu": 34, "timerw": 35, "sci3": 37, "adc": 38,
}

LIBRARY = r"""
; ---------------------------------------------------------------- system
unexpected:
    mov.w @UNEXPECTED, r0
    inc.w #1, r0
    mov.w r0, @UNEXPECTED
    pop.w r0
    rte

; Direct transitions always end in direct-transition interrupt exception
; handling (REJ09B0152-0300 §5.3); the handler only returns.
direct_isr:
    rte

; WatchdogStart: unlock, enable, reload on phiW/256 (2 s overflow).
wdt_start:
    mov.b #0x9e, r0l
    mov.b r0l, @TCSRWD1:8
    mov.b #0xa6, r0l
    mov.b r0l, @TCSRWD1:8
    mov.b #0x8e, r0l
    mov.b r0l, @TCSRWD1:8
    mov.b #0xf5, r0l
    mov.b r0l, @TMWD:8
    rts

; WatchdogService.
wdt_kick:
    mov.b #0x5e, r0l
    mov.b r0l, @TCSRWD1:8
    sub.b r0l, r0l
    mov.b r0l, @TCWD:8
    mov.b #0x9e, r0l
    mov.b r0l, @TCSRWD1:8
    rts

; HardwareSetup: shared SSU bus in mode 3, main clock / 4, devices deselected.
hw_setup:
    bset #4, @CKSTPR2:8
    mov.b @SSCRL, r0l
    or.b #0x40, r0l
    mov.b r0l, @SSCRL
    mov.b #0x86, r0l
    mov.b r0l, @SSMR
    mov.b #0x8c, r0l
    mov.b r0l, @SSCRH
    mov.b #8, r0l
    mov.b r0l, @PUCR9
    mov.b #1, r0l
    mov.b r0l, @PCR9:8
    mov.b #7, r0l
    mov.b r0l, @PCR1:8
    mov.b #5, r0l
    mov.b r0l, @PDR1:8
    bset #0, @PDR9:8
    mov.b #1, r0l
    mov.b r0l, @PMRB:8
    mov.b #0x80, r0l
    mov.b r0l, @SSER
    rts

; TimerB1Init: auto-reload phiW/256 from 0xF8 gives a 16 Hz interrupt.
tb1_init:
    bset #2, @CKSTPR1:8
    mov.b #0xbf, r0l
    mov.b r0l, @TMB1
    mov.b #0xf8, r0l
    mov.b r0l, @TCB1
    bclr #2, @IRR2:8
    bset #2, @IENR2:8
    mov.b @TMB1, r0l
    or.b #0x40, r0l
    mov.b r0l, @TMB1
    rts

; RTC in 24-hour mode on the 32.768 kHz source with the quarter-second
; periodic interrupt enabled, as RtcRestore leaves it.
rtc_init:
    bset #0, @CKSTPR1:8
    mov.b #0x10, r0l
    mov.b r0l, @RTCCR1
    sub.b r0l, r0l
    mov.b r0l, @RTCCR1
    mov.b #0x08, r0l
    mov.b r0l, @RTCCSR
    mov.b #0x1d, r0l
    mov.b r0l, @RTCCR2
    mov.b #0xc0, r0l
    mov.b r0l, @RTCCR1
    bset #7, @IENR1:8
    rts

; ClockSleep(NORMAL): watch mode, wake into subactive mode at phiW.
sleep_watch_sub:
    mov.b #0xaf, r0l
    mov.b r0l, @SYSCR1:8
    mov.b #0xe3, r0l
    mov.b r0l, @SYSCR2:8
    sleep
    rts

; ClockSleep(LOW_POWER): watch mode, wake into active high-speed mode.
sleep_watch_active:
    mov.b #0xa7, r0l
    mov.b r0l, @SYSCR1:8
    mov.b #0xe0, r0l
    mov.b r0l, @SYSCR2:8
    sleep
    rts

; Sleep (high-speed) mode: CPU halts, peripherals keep running.
sleep_idle:
    mov.b #0x07, r0l
    mov.b r0l, @SYSCR1:8
    mov.b #0xe0, r0l
    mov.b r0l, @SYSCR2:8
    sleep
    rts

; ------------------------------------------------------------------- SSU
; Send r0l once the transmit register is empty. These helpers use only r0
; so that pointers in er1..er3 survive.
ssu_put:
    mov.b @SSSR, r0h
    btst #2, r0h
    beq ssu_put
    mov.b r0l, @SSTDR
    rts

; Wait for the end of transmission.
ssu_end:
    mov.b @SSSR, r0h
    btst #3, r0h
    beq ssu_end
    rts

; Wait for a received byte into r0l; an overrun is counted and cleared.
ssu_get:
    mov.b @SSSR, r0h
    btst #6, r0h
    bne 1f
    btst #1, r0h
    beq ssu_get
    mov.b @SSRDR, r0l
    rts
1:  bclr #6, r0h
    mov.b r0h, @SSSR
    push.w r1
    mov.w @OVERRUNS, r1
    inc.w #1, r1
    mov.w r1, @OVERRUNS
    pop.w r1
    mov.b @SSRDR, r0l
    rts

; Restart the SSU for full-duplex transfers with clean flags.
ssu_duplex:
    mov.b @SSER, r0l
    and.b #0x3f, r0l
    mov.b r0l, @SSER
    sub.b r0l, r0l
    mov.b r0l, @SSSR
    mov.b @SSER, r0l
    or.b #0xc0, r0l
    mov.b r0l, @SSER
    rts

; ------------------------------------------------------------ BMA150 (SPI)
; AccelRead: r0l register, er2 destination, r3l count (> 0).
accel_read:
    push.w r0
    mov.b @SSSR, r0l
    and.b #4, r0l
    mov.b r0l, @SSSR
    mov.b #0xc0, r0l
    mov.b r0l, @SSER
    pop.w r0
    or.b #0x80, r0l
    bclr #0, @PDR9:8
    jsr @ssu_put
    jsr @ssu_get
1:  mov.b #0xff, r0l
    jsr @ssu_put
    jsr @ssu_get
    mov.b r0l, @er2
    adds #1, er2
    dec.b r3l
    bne 1b
    jsr @ssu_end
    bset #0, @PDR9:8
    mov.b #0x80, r0l
    mov.b r0l, @SSER
    rts

; AccelWrite: r0l register, r0h value. Clobbers r2h.
accel_write:
    mov.b r0h, r2h
    mov.b #0x80, r1l
    mov.b r1l, @SSER
    bclr #0, @PDR9:8
    jsr @ssu_put
    mov.b r2h, r0l
    jsr @ssu_put
    jsr @ssu_end
    bset #0, @PDR9:8
    rts

; AccelInit: four-wire SPI, +/-2 g at 1500 Hz, EE_W window for register 0x1E.
accel_init:
    mov.b @SSSR, r0l
    and.b #4, r0l
    mov.b r0l, @SSSR
    mov.w #0x1580, r0
    jsr @accel_write
    mov.b #0x00, r0l
    mov.l #0xf810, er2
    mov.b #2, r3l
    jsr @accel_read
    mov.b #0x14, r0l
    mov.l #0xf810, er2
    mov.b #1, r3l
    jsr @accel_read
    mov.b @0xf810, r0h
    and.b #0xe0, r0h
    or.b #0x06, r0h
    mov.b #0x14, r0l
    jsr @accel_write
    mov.w #0x0b00, r0
    jsr @accel_write
    mov.w #0x0a10, r0
    jsr @accel_write
    mov.b #0x1e, r0l
    mov.l #0xf810, er2
    mov.b #1, r3l
    jsr @accel_read
    mov.b @0xf810, r0h
    or.b #0x80, r0h
    mov.b #0x1e, r0l
    jsr @accel_write
    mov.w #0x0a00, r0
    jsr @accel_write
    rts

; CaptureSample, entered in subactive mode: wake the sensor over the
; subclock-driven SSU, service the watchdog, make a direct transition to
; active high-speed mode, read X/Y/Z and put the sensor back to sleep.
; The six data registers land at 0xF818..0xF81D.
capture:
    mov.b #0x87, r0l
    mov.b r0l, @SSMR
    mov.b #0x80, r0l
    mov.b r0l, @SSER
    bclr #0, @PDR9:8
    mov.b #0x0a, r0l
    jsr @ssu_put
    sub.b r0l, r0l
    jsr @ssu_put
    jsr @ssu_end
    bset #0, @PDR9:8
    jsr @wdt_kick
    mov.b #0xa7, r0l
    mov.b r0l, @SYSCR1:8
    mov.b #0xeb, r0l
    mov.b r0l, @SYSCR2:8
    sleep
    mov.b #0x86, r0l
    mov.b r0l, @SSMR
    mov.b #0x02, r0l
    mov.l #0xf818, er2
    mov.b #6, r3l
    jsr @accel_read
    mov.w #0x0a01, r0
    jsr @accel_write
    rts

; ---------------------------------------------------------- M95512 (SPI)
; Poll the status register until the write-in-progress bit clears, then
; leave the bus restarted for the next command. Chip select stays high.
eep_ready:
    jsr @ssu_duplex
    bclr #2, @PDR1:8
    mov.b #0x05, r0l
    jsr @ssu_put
    jsr @ssu_get
1:  mov.b #0xff, r0l
    jsr @ssu_put
    jsr @ssu_get
    btst #0, r0l
    bne 1b
    jsr @ssu_end
    bset #2, @PDR1:8
    rts

; EepromRead: r1 EEPROM address, er2 destination, r3 count (> 0).
eep_read:
    push.w r1
    jsr @wdt_kick
    bset #4, @CKSTPR2:8
    sub.b r0l, r0l
    mov.b r0l, @SSER
    mov.b #0x86, r0l
    mov.b r0l, @SSMR
    jsr @eep_ready
    jsr @ssu_duplex
    bclr #2, @PDR1:8
    mov.b #0x03, r0l
    jsr @ssu_put
    jsr @ssu_get
    pop.w r1
    mov.b r1h, r0l
    jsr @ssu_put
    jsr @ssu_get
    mov.b r1l, r0l
    jsr @ssu_put
    jsr @ssu_get
1:  mov.b #0xff, r0l
    jsr @ssu_put
    jsr @ssu_get
    mov.b r0l, @er2
    adds #1, er2
    dec.w #1, r3
    bne 1b
    jsr @ssu_end
    bset #2, @PDR1:8
    mov.b #0x80, r0l
    mov.b r0l, @SSER
    rts

; EepromWrite: r1 EEPROM address, er2 source, r3 count (> 0). Spans are
; split at 128-byte page boundaries; each page waits for the previous write.
eep_write:
    push.w r4
    mov.w r1, r4
    jsr @wdt_kick
    bset #4, @CKSTPR2:8
    sub.b r0l, r0l
    mov.b r0l, @SSER
    mov.b #0x86, r0l
    mov.b r0l, @SSMR
1:  jsr @eep_ready
    mov.b @SSER, r0l
    and.b #0x3f, r0l
    mov.b r0l, @SSER
    sub.b r0l, r0l
    mov.b r0l, @SSSR
    mov.b #0x80, r0l
    mov.b r0l, @SSER
    bclr #2, @PDR1:8
    mov.b #0x06, r0l
    jsr @ssu_put
    jsr @ssu_end
    bset #2, @PDR1:8
    bclr #2, @PDR1:8
    mov.b #0x02, r0l
    jsr @ssu_put
    mov.b r4h, r0l
    jsr @ssu_put
    mov.b r4l, r0l
    jsr @ssu_put
2:  mov.b @er2+, r0l
    jsr @ssu_put
    inc.w #1, r4
    dec.w #1, r3
    beq 3f
    mov.b r4l, r0l
    and.b #0x7f, r0l
    bne 2b
    jsr @ssu_end
    bset #2, @PDR1:8
    bra 1b
3:  jsr @ssu_end
    bset #2, @PDR1:8
    mov.b #0x80, r0l
    mov.b r0l, @SSER
    pop.w r4
    rts

; ---------------------------------------------------------- NT7508 (SPI)
; Send r2l command bytes from er1 with A0 low.
lcd_cmds:
    mov.b #0x80, r0l
    mov.b r0l, @SSER
    bclr #0, @PDR1:8
    bclr #1, @PDR1:8
1:  mov.b @er1+, r0l
    jsr @ssu_put
    dec.b r2l
    bne 1b
    jsr @ssu_end
    bset #0, @PDR1:8
    rts

; Address column r0l (0..127) of page r0h in the drawing bank. CS stays low.
lcd_address:
    bclr #1, @PDR1:8
    mov.b r0l, r3l
    mov.b r0h, r3h
    shlr.b r0l
    shlr.b r0l
    shlr.b r0l
    shlr.b r0l
    and.b #7, r0l
    or.b #0x10, r0l
    jsr @ssu_put
    mov.b r3l, r0l
    and.b #15, r0l
    jsr @ssu_put
    mov.b @BANK, r0l
    shll.b r0l
    shll.b r0l
    shll.b r0l
    add.b r3h, r0l
    add.b #0xb0, r0l
    jsr @ssu_put
    jsr @ssu_end
    bset #1, @PDR1:8
    rts

; DisplayClear(64): zero 96 columns of all eight pages of the drawing bank.
lcd_clear:
    mov.b #0x80, r0l
    mov.b r0l, @SSER
    bclr #0, @PDR1:8
    sub.b r2h, r2h
1:  sub.b r0l, r0l
    mov.b r2h, r0h
    jsr @lcd_address
    mov.b #96, r2l
    sub.b r0l, r0l
2:  mov.b @SSSR, r1h
    btst #2, r1h
    beq 2b
    mov.b r0l, @SSTDR
3:  mov.b @SSSR, r1h
    btst #2, r1h
    beq 3b
    mov.b r0l, @SSTDR
    dec.b r2l
    bne 2b
    jsr @ssu_end
    inc.b r2h
    cmp.b #8, r2h
    blo 1b
    bset #0, @PDR1:8
    rts

; DisplayBlit of a page-aligned raster: er1 source (two plane bytes per
; column), r2l column, r2h first page, r3l width, r3h page count.
lcd_blit:
    push.w r4
    push.w r5
    mov.w r2, r4
    mov.w r3, r5
    mov.b #0x80, r0l
    mov.b r0l, @SSER
    bclr #0, @PDR1:8
1:  mov.b r4l, r0l
    mov.b r4h, r0h
    jsr @lcd_address
    mov.b r5l, r2l
2:  mov.b @er1+, r0l
    jsr @ssu_put
    mov.b @er1+, r0l
    jsr @ssu_put
    dec.b r2l
    bne 2b
    jsr @ssu_end
    inc.b r4h
    dec.b r5h
    bne 1b
    bset #0, @PDR1:8
    pop.w r5
    pop.w r4
    rts

; DisplayToggleBank: show the drawing bank, then draw into the other one.
lcd_toggle:
    mov.b #0x80, r0l
    mov.b r0l, @SSER
    bclr #0, @PDR1:8
    bclr #1, @PDR1:8
    mov.b #0x40, r0l
    jsr @ssu_put
    mov.b @BANK, r0l
    shll.b r0l
    shll.b r0l
    shll.b r0l
    shll.b r0l
    shll.b r0l
    shll.b r0l
    jsr @ssu_put
    jsr @ssu_end
    bset #0, @PDR1:8
    mov.b @BANK, r0l
    xor.b #1, r0l
    mov.b r0l, @BANK
    rts

; DisplayInit from the resident script: power-save exit, panel setup, both
; banks cleared, display on.
lcd_init:
    mov.l #lcd_script, er1
    mov.b #lcd_script_end - lcd_script, r2l
    jsr @lcd_cmds
    mov.b #1, r0l
    mov.b r0l, @BANK
    jsr @lcd_clear
    sub.b r0l, r0l
    mov.b r0l, @BANK
    jsr @lcd_clear
    mov.l #lcd_on, er1
    mov.b #1, r2l
    jmp @lcd_cmds

lcd_script:
    .byte 0xe1, 0x48, 0x40, 0xa0, 0xc0, 0x44, 0x20, 0xab, 0x67, 0x25, 0x81, 0x18
    .byte 0x52, 0x95, 0x88, 0x00, 0x89, 0x00, 0x8a, 0x55, 0x8b, 0x55, 0x8c, 0x77
    .byte 0x8d, 0x77, 0x8e, 0x99, 0x8f, 0x99, 0x4c, 0x04, 0xf1, 0x00, 0xf7, 0x02
    .byte 0xf6, 0x0a, 0x2f, 0x40, 0x00, 0xa6, 0x81, 0x14
lcd_script_end:
lcd_on:
    .byte 0xaf
lcd_sleep:
    .byte 0xa9
    .align 2
"""


def program(body: str, handlers: dict[str, str], symbols: dict | None = None,
            listing: Listing | None = None, seed: int = 0) -> tuple[bytes, dict]:
    """Assemble a guest: vectors, ``start`` near 0x100, ``body`` and the library.

    The seed moves the whole program by up to 2 KiB, so a guest's code bytes
    and addresses differ between runs with different seeds.

    ``handlers`` maps vector names from VECTORS to labels; the direct-transition
    vector defaults to a bare RTE. Every other vector
    points at a stub that records its number at 0xF7FB and counts the entry
    at UNEXPECTED.
    """
    handlers = {"direct": "direct_isr", **handlers}
    assigned = {VECTORS[name]: label for name, label in handlers.items()}
    lines = [EQUATES, ".vector 0, start"]
    stubs = []
    for number in range(1, 40):
        if number in (1, 2, 3, 4, 5, 6):
            continue
        if number in assigned:
            lines.append(f".vector {number}, {assigned[number]}")
        else:
            lines.append(f".vector {number}, unexpected_{number}")
            stubs += [f"unexpected_{number}:", "    push.w r0", f"    mov.b #{number}, r0l",
                      "    mov.b r0l, @0xf7fb", "    jmp @unexpected"]
    lines += [f".org {0x100 + 2 * (seed % 1024):#x}", "start:", "    mov.l #0xff80, er7", body,
              LIBRARY, *stubs]
    return assemble("\n".join(lines), symbols, listing)
