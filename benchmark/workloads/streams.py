"""Device streams: the serial paths driven back to back at their documented rates.

Hardware-tier workloads in the free-running shape (see ``benchmark.freerun``).
Each item picks its parameters from the item number and the seed, including
the serial clock, so every clock setting is exercised and an emulator cannot
specialise for one rate.

- lcd-stream: a 32-column, 8-page raster from an LCG into the NT7508's
  drawing bank over the SSU, then a bank toggle. The bank last drawn is
  checked column by column.
- eeprom-stream: M95512 page writes (WREN, WRITE, status polling until the
  write cycle ends) and page reads over the SSU, on a pool of 64 pages that
  starts with seeded contents. Read digests and the whole pool are checked.
- ir-stream: SCI3 transmit bursts in IrDA mode at a per-item bit rate, with
  the receiver enabled beside the transmitter as the retail IrConfigure
  leaves it, and receive status cleared after each burst.

Item durations are bounded by the documented clocks: at least the bytes on
the wire at the configured serial clock (SSU: 8 bits per byte at the CKS
division of SSMR, REJ09B0152-0300 §15.3.3; SCI3: 10 bits per byte at
(BRR + 1) * 32 states per bit with SMR3 = 0, §14.3.9), and at most that plus
all of the item's CPU work done serially, one clock of start-up latency and
one polling pass per wait, plus the M95512's maximum write time (5 ms, ST
DS4192) per page write. Transfers cannot overlap on one serial line, so a
target whose serial blocks are faster than their clocks fails, and one that
is slower or stalls fails the upper bound.
"""

from __future__ import annotations

import random
from functools import lru_cache

from ..freerun import HORIZONS, FreeRun
from ..runtime import PHI
from ..workload import Workload, compare_memory
from .ui import Panel

M16 = 0xFFFF
SSU_DIVISOR = {0: 256, 1: 128, 2: 64, 3: 32, 4: 16, 5: 8, 6: 4}  # SSMR CKS2..0: phi/n
WRITE_CYCLE_STATES = 5 * PHI // 1000  # M95512 tW, 5 ms maximum.


def lcg(x: int, count: int) -> list[int]:
    out = []
    for _ in range(count):
        x = (x * 25173 + 13849) & M16
        out.append(x)
    return out


SEND = r"""
; Send r0l once the transmit register is empty.
b_send:
send:
    mov.b @SSSR, r1h
    btst #2, r1h
    beq send
b_send_write:
    mov.b r0l, @SSTDR
    rts

; Wait for the end of transmission.
b_tend:
tend:
    mov.b @SSSR, r1h
    btst #3, r1h
    beq tend
b_tend_ret:
    rts
"""

PARAMS = r"""
    mov.w #MULT, r1
    mulxu.w r1, er0
    add.w #ADD, r0
    mov.w r0, r4
    ; Serial clock for this item from the table, indexed by v mod 8.
    mov.b r4l, r1l
    and.b #7, r1l
    sub.l er2, er2
    mov.b r1l, r2l
    add.l #CLOCKS, er2
    mov.b @er2, r5l
"""


class Stream(FreeRun):
    clocks_choice: tuple[int, ...] = (2, 3, 4, 5, 6)

    def __init__(self, name: str, body: str, routines: str, seed: int, setup: str):
        rng = random.Random(f"{name}:{seed}")
        self.mult = rng.randrange(1, 0x10000, 2)
        self.add = rng.randrange(0x10000)
        self.clocks = [rng.choice(self.clocks_choice) for _ in range(8)]
        self.seed = seed
        body = (PARAMS + body).replace("#MULT", f"#{self.mult}").replace("#ADD", f"#{self.add}")
        routines += "\n    .align 2\nCLOCKS:\n    .byte " + ", ".join(map(str, self.clocks)) + "\n"
        super().__init__(body, routines, seed, setup=setup)
        self.poll = {name: self.block[name] for name in self.block}

    def v(self, c: int) -> int:
        return (c * self.mult + self.add) & M16

    def bounds(self, counts: dict, wire: int, waits: int, wait_bound: int,
               extra: int = 0) -> tuple[int, int]:
        cpu = self.states(counts)
        return wire, cpu + waits * wait_bound + extra


LCD_BODY = r"""
LBUF = 0xfa00
    ; 256 raster words from the LCG.
    mov.w r4, r0
    mov.l #LBUF, er2
    mov.w #256, r3
    mov.w #25173, r1
b_gen:
    mulxu.w r1, er0
    add.w #13849, r0
    mov.w r0, @er2
    adds #2, er2
    dec.w #1, r3
    bne b_gen
b_draw:
    ; Clock change with the SSU idle, then select the panel.
    sub.b r0l, r0l
    mov.b r0l, @SSER
    mov.b r5l, r0l
    or.b #0x80, r0l
    mov.b r0l, @SSMR
    mov.b #0x80, r0l
    mov.b r0l, @SSER
    bclr #0, @PDR1:8
    ; Column x = (v >> 8) mod 64.
    mov.b r4h, r6l
    and.b #63, r6l
    sub.b r6h, r6h
    mov.l #LBUF, er2
b_page:
    bclr #1, @PDR1:8
    mov.b r6l, r0l
    shlr.b r0l
    shlr.b r0l
    shlr.b r0l
    shlr.b r0l
    or.b #0x10, r0l
    jsr @send
b_page_2:
    mov.b r6l, r0l
    and.b #15, r0l
    jsr @send
b_page_3:
    mov.b @BANK, r0l
    shll.b r0l
    shll.b r0l
    shll.b r0l
    add.b r6h, r0l
    add.b #0xb0, r0l
    jsr @send
b_page_4:
    jsr @tend
b_page_5:
    bset #1, @PDR1:8
    mov.b #64, r3l
b_data:
    mov.b @er2+, r0l
    jsr @send
b_data_next:
    dec.b r3l
    bne b_data
b_page_end:
    jsr @tend
b_page_next:
    inc.b r6h
    cmp.b #8, r6h
    blo b_page
b_toggle:
    bclr #1, @PDR1:8
    mov.b #0x40, r0l
    jsr @send
b_toggle_2:
    mov.b @BANK, r0l
    shll.b r0l
    shll.b r0l
    shll.b r0l
    shll.b r0l
    shll.b r0l
    shll.b r0l
    jsr @send
b_toggle_3:
    jsr @tend
b_toggle_4:
    bset #0, @PDR1:8
    mov.b @BANK, r0l
    xor.b #1, r0l
    mov.b r0l, @BANK
    ; Digest: the item's parameter word and clock.
    mov.w r4, r1
    extu.l er1
    mov.b r5l, r0l
    extu.w r0
    extu.l er0
    shll.l er0
    shll.l er0
    shll.l er0
    shll.l er0
    shll.l er0
    shll.l er0
    shll.l er0
    shll.l er0
    shll.l er0
    shll.l er0
    shll.l er0
    shll.l er0
    shll.l er0
    shll.l er0
    shll.l er0
    shll.l er0
    add.l er0, er1
"""

LCD_SETUP = r"""
    jsr @hw_setup
    jsr @lcd_init
"""


class LcdStream(Stream):
    def __init__(self, seed: int):
        super().__init__("lcd-stream", LCD_BODY, SEND, seed, LCD_SETUP)
        self.frames: dict[int, tuple[int, bytes]] = {}

    @lru_cache(maxsize=None)
    def frame(self, c: int) -> tuple[int, bytes]:
        v = self.v(c)
        words = lcg(v, 256)
        return (v >> 8) & 63, b"".join(w.to_bytes(2, "big") for w in words)

    @lru_cache(maxsize=4096)
    def item(self, c: int):
        v = self.v(c)
        cks = self.clocks[v & 7]
        byte = 8 * SSU_DIVISOR[cks]
        counts = {"b_gen": 256, "b_draw": 1, "b_page": 8, "b_page_2": 8, "b_page_3": 8,
                  "b_page_4": 8, "b_page_5": 8, "b_data": 512, "b_data_next": 512,
                  "b_page_end": 8, "b_page_next": 8, "b_toggle": 1, "b_toggle_2": 1,
                  "b_toggle_3": 1, "b_toggle_4": 1, "b_send": 538, "b_send_write": 538,
                  "b_tend": 17, "b_tend_ret": 17}
        sent = 8 * (3 + 64) + 2
        wait = byte + SSU_DIVISOR[cks] + self.block["b_send"]
        low, high = self.bounds(counts, sent * byte, sent + 17, wait)
        return (v + (cks << 16)) & 0xFFFFFFFF, low, high

    def extra(self, c: int, observed: dict) -> list[str]:
        # Item c drew bank (c - 1) mod 2; later items of that parity overwrite it.
        bank = (c - 1) % 2
        covered = [[False] * 96 for _ in range(8)]
        panel = Panel()
        remaining = 96 * 8
        for i in range(c, 0, -2):
            x, data = self.frame(i)
            for page in range(8):
                for col in range(x, x + 32):
                    if not covered[page][col]:
                        covered[page][col] = True
                        remaining -= 1
                        base = (bank * 8 + page) * 256 + 2 * col
                        offset = page * 64 + 2 * (col - x)
                        panel.ram[base:base + 2] = data[offset:offset + 2]
            if not remaining:
                break
        expected = {f"{(bank * 8 + page) * 256:04x}":
                    panel.ram[(bank * 8 + page) * 256:(bank * 8 + page) * 256 + 192].hex()
                    for page in range(8)}
        return compare_memory({"lcd": expected}, observed)


EEPROM_BODY = r"""
RBUF = 0xfb00
WBUF = 0xfc00
    ; x = LCG(v): page (x >> 4) mod 64, a write if bit 15 is set.
    mov.w r4, r0
    mov.w #25173, r1
    mulxu.w r1, er0
    add.w #13849, r0
    mov.w r0, r6
    ; EEPROM address 0x8000 + 128 * page in r3.
    mov.w r6, r3
    shlr.w r3
    shlr.w r3
    shlr.w r3
    shlr.w r3
    and.w #63, r3
    shll.w r3
    shll.w r3
    shll.w r3
    shll.w r3
    shll.w r3
    shll.w r3
    shll.w r3
    or.w #0x8000, r3
    ; Clock change with the SSU idle.
    sub.b r0l, r0l
    mov.b r0l, @SSER
    mov.b r5l, r0l
    or.b #0x80, r0l
    mov.b r0l, @SSMR
    btst #7, r6h
    bne b_write
b_read:
    jsr @duplex
b_read_2:
    bclr #2, @PDR1:8
    mov.b #3, r0l
    jsr @xfer
b_read_3:
    mov.b r3h, r0l
    jsr @xfer
b_read_4:
    mov.b r3l, r0l
    jsr @xfer
b_read_5:
    mov.l #RBUF, er2
    mov.b #128, r3l
b_read_byte:
    mov.b #0xff, r0l
    jsr @xfer
b_read_store:
    mov.b r0l, @er2
    adds #1, er2
    dec.b r3l
    bne b_read_byte
b_read_end:
    jsr @tend
b_read_6:
    bset #2, @PDR1:8
    ; Digest: rotate-xor of the 64 words read.
    mov.l #RBUF, er2
    mov.b #64, r3l
    sub.w r1, r1
b_read_hash:
    mov.w @er2+, r0
    rotl.w r1
    xor.w r0, r1
    dec.b r3l
    bne b_read_hash
b_read_done:
    extu.l er1
    jmp @b_ring
b_write:
    ; 64 data words from the LCG after x.
    mov.w r6, r0
    mov.l #WBUF, er2
    mov.b #64, r6l
    mov.w #25173, r1
b_write_gen:
    mulxu.w r1, er0
    add.w #13849, r0
    mov.w r0, @er2
    adds #2, er2
    dec.b r6l
    bne b_write_gen
b_write_2:
    sub.b r0l, r0l
    mov.b r0l, @SSSR
    mov.b #0x80, r0l
    mov.b r0l, @SSER
    bclr #2, @PDR1:8
    mov.b #6, r0l
    jsr @send
b_write_3:
    jsr @tend
b_write_4:
    bset #2, @PDR1:8
    bclr #2, @PDR1:8
    mov.b #2, r0l
    jsr @send
b_write_5:
    mov.b r3h, r0l
    jsr @send
b_write_6:
    mov.b r3l, r0l
    jsr @send
b_write_7:
    mov.l #WBUF, er2
    mov.b #128, r3l
b_write_byte:
    mov.b @er2+, r0l
    jsr @send
b_write_next:
    dec.b r3l
    bne b_write_byte
b_write_end:
    jsr @tend
b_write_8:
    bset #2, @PDR1:8
    jsr @duplex
b_poll:
    bclr #2, @PDR1:8
    mov.b #5, r0l
    jsr @xfer
b_poll_2:
    mov.b #0xff, r0l
    jsr @xfer
b_poll_3:
    mov.b r0l, r6l
    jsr @tend
b_poll_4:
    bset #2, @PDR1:8
    btst #0, r6l
    bne b_poll
b_write_done:
    ; Digest: the item's parameter word with bit 31 marking a write.
    mov.w r4, r1
    extu.l er1
    mov.w #0x8000, r0
    mov.w r0, e1
"""

EEPROM_ROUTINES = SEND + r"""
; Restart the SSU for full-duplex transfers with clean flags.
b_duplex:
duplex:
    sub.b r0l, r0l
    mov.b r0l, @SSER
    mov.b r0l, @SSSR
    mov.b #0xc0, r0l
    mov.b r0l, @SSER
    rts

; Send r0l and return the byte received meanwhile in r0l.
b_xfer:
xfer:
    mov.b @SSSR, r1h
    btst #2, r1h
    beq xfer
b_xfer_put:
    mov.b r0l, @SSTDR
b_xfer_get:
    mov.b @SSSR, r1h
    btst #1, r1h
    beq b_xfer_get
b_xfer_read:
    mov.b @SSRDR, r0l
    rts
"""

POOL = 0x8000


class EepromStream(Stream):
    def __init__(self, seed: int):
        super().__init__("eeprom-stream", EEPROM_BODY, EEPROM_ROUTINES, seed,
                         "    jsr @hw_setup\n")
        rng = random.Random(f"eeprom-stream-image:{seed}")
        image = bytearray([0xFF]) * 65536
        image[POOL:POOL + 64 * 128] = bytes(rng.randrange(256) for _ in range(64 * 128))
        self.initial = bytes(image)
        # writer[p] = last item that wrote page p, simulated incrementally.
        self.simulated = 0
        self.writer = [0] * 64
        self.reads: dict[int, int] = {}

    def op(self, c: int) -> tuple[int, bool, int]:
        x = (self.v(c) * 25173 + 13849) & M16
        return (x >> 4) & 63, bool(x & 0x8000), x

    @lru_cache(maxsize=None)
    def page_data(self, c: int) -> bytes:
        if c == 0:
            raise ValueError
        _p, _w, x = self.op(c)
        return b"".join(w.to_bytes(2, "big") for w in lcg(x, 64))

    def content(self, page: int, writer: int) -> bytes:
        if writer == 0:
            return self.initial[POOL + 128 * page:POOL + 128 * page + 128]
        return self.page_data(writer)

    def simulate(self, c: int):
        """Advance the page writers to item c, recording each read's digest."""
        while self.simulated < c:
            i = self.simulated + 1
            page, write, _x = self.op(i)
            if write:
                self.writer[page] = i
            else:
                self.reads[i] = self.writer[page]
            self.simulated = i
        if c < self.simulated - 4096:
            raise ValueError("eeprom-stream check out of order")

    def history(self, c: int) -> list[int]:
        """Page writers after item c (replays from the start when needed)."""
        if c < self.simulated:
            self.simulated, self.writer, self.reads = 0, [0] * 64, {}
        self.simulate(c)
        return list(self.writer)

    @lru_cache(maxsize=4096)
    def item(self, c: int):
        v = self.v(c)
        cks = self.clocks[v & 7]
        div = SSU_DIVISOR[cks]
        byte = 8 * div
        page, write, _x = self.op(c)
        if write:
            counts = {"b_write": 1, "b_write_gen": 64, "b_write_2": 1, "b_write_3": 1,
                      "b_write_4": 1, "b_write_5": 1, "b_write_6": 1, "b_write_7": 1,
                      "b_write_byte": 128, "b_write_next": 128, "b_write_end": 1,
                      "b_write_8": 1, "b_poll": 1, "b_poll_2": 1, "b_poll_3": 1,
                      "b_poll_4": 1, "b_write_done": 1, "b_send": 132, "b_send_write": 132,
                      "b_tend": 3, "b_tend_ret": 3, "b_duplex": 1, "b_xfer": 2,
                      "b_xfer_put": 2, "b_xfer_get": 2, "b_xfer_read": 2}
            sent, waits = 132 + 2, 132 + 2 * 2 + 3
            # Status polls until the write cycle ends: at most the write time
            # plus one more poll transaction.
            poll = (self.block["b_poll"] + self.block["b_poll_2"] + self.block["b_poll_3"]
                    + self.block["b_poll_4"] + self.block["b_tend"] + self.block["b_tend_ret"]
                    + 2 * (self.block["b_xfer"] + self.block["b_xfer_put"]
                           + self.block["b_xfer_get"] + self.block["b_xfer_read"])
                    + 3 * (byte + div + self.block["b_xfer"]))
            extra = WRITE_CYCLE_STATES + poll
            digest = 0x80000000 | v
        else:
            counts = {"b_read": 1, "b_read_2": 1, "b_read_3": 1, "b_read_4": 1,
                      "b_read_5": 1, "b_read_byte": 128, "b_read_store": 128,
                      "b_read_end": 1, "b_read_6": 1, "b_read_hash": 64, "b_read_done": 1,
                      "b_duplex": 1, "b_xfer": 131, "b_xfer_put": 131, "b_xfer_get": 131,
                      "b_xfer_read": 131, "b_tend": 1, "b_tend_ret": 1}
            sent, waits, extra = 131, 2 * 131 + 1, 0
            self.history(c - 1)
            data = self.content(page, self.writer[page])
            digest = 0
            for k in range(0, 128, 2):
                digest = (((digest << 1) | (digest >> 15)) & M16) ^ int.from_bytes(
                    data[k:k + 2], "big")
        for name in set(self.block) - {"b_item", "b_ring", "wdt_kick", "b_end"}:
            counts.setdefault(name, 0)
        wait = byte + div + max(self.block["b_send"], self.block["b_xfer"],
                                self.block["b_xfer_get"])
        low, high = self.bounds(counts, sent * byte, waits, wait, extra)
        return digest, low, high

    def extra(self, c: int, observed: dict) -> list[str]:
        writers = self.history(c)
        expected = {}
        page, write, _x = self.op(c + 1)
        for p in range(64):
            # Item c+1 may be in its write cycle, when the page's cells are
            # undefined (DS4192: reads are not accepted while WIP is set).
            if not (write and p == page):
                expected[f"{POOL + 128 * p:04x}"] = self.content(p, writers[p]).hex()
        return compare_memory({"eeprom": expected}, observed)


IR_BODY = r"""
    ; Bit rate: BRR = table[v mod 8]; burst of 16 + (v >> 8) mod 32 bytes.
    sub.b r0l, r0l
    mov.b r0l, @SCR3
    mov.b r5l, @BRR3
    ; At least one bit period before enabling the transmitter (§14.4).
    mov.b r5l, r3l
    inc.b r3l
b_ir_delay:
    mov.b #6, r3h
b_ir_delay_inner:
    dec.b r3h
    bne b_ir_delay_inner
b_ir_delay_next:
    dec.b r3l
    bne b_ir_delay
b_ir_start:
    ; Transmitter and receiver enabled together, as IrConfigure leaves SCR3.
    mov.b #0x30, r0l
    mov.b r0l, @SCR3
    mov.b r4h, r3l
    and.b #31, r3l
    add.b #16, r3l
    mov.w r4, r0
    mov.w #25173, r1
b_ir_byte:
    mulxu.w r1, er0
    add.w #13849, r0
b_ir_poll:
    mov.b @SSR3, r2l
    btst #7, r2l
    beq b_ir_poll
b_ir_write:
    mov.b r0h, @TDR3
    dec.b r3l
    bne b_ir_byte
b_ir_end:
    mov.b @SSR3, r2l
    btst #2, r2l
    beq b_ir_end
b_ir_done:
    ; Clear receive status as IrProtocolTick does (SSR3 &= 0xc4).
    mov.b @SSR3, r2l
    and.b #0xc4, r2l
    mov.b r2l, @SSR3
    mov.w r4, r1
    extu.l er1
    mov.b r5l, r0l
    mov.b r0l, r0h
    sub.b r0l, r0l
    mov.w r0, e1
"""

IR_SETUP = r"""
    ; IrConfigure: SCI3 on, IrDA at phi, 8N1, transmitter configured per item.
    mov.b #3, r0l
    mov.b r0l, @0xf088
    bset #6, @CKSTPR1:8
    mov.b #1, r0l
    mov.b r0l, @SPCR
    sub.b r0l, r0l
    mov.b r0l, @SEMR
    mov.b r0l, @SCR3
    mov.b r0l, @SMR3
    mov.b #0x80, r0l
    mov.b r0l, @IRCR
    mov.b #0x11, r0l
    mov.b r0l, @SPCR
"""


class IrStream(Stream):
    clocks_choice = (0, 1, 2, 3, 5, 7, 11)

    def __init__(self, seed: int):
        super().__init__("ir-stream", IR_BODY, "", seed, IR_SETUP)

    @lru_cache(maxsize=4096)
    def item(self, c: int):
        v = self.v(c)
        brr = self.clocks[v & 7]
        count = 16 + ((v >> 8) & 31)
        bit = 32 * (brr + 1)
        byte = 10 * bit
        counts = {"b_ir_delay": brr + 1, "b_ir_delay_inner": 6 * (brr + 1),
                  "b_ir_delay_next": brr + 1, "b_ir_start": 1, "b_ir_byte": count,
                  "b_ir_poll": count, "b_ir_write": count, "b_ir_end": 1, "b_ir_done": 1}
        wait = byte + bit + self.block["b_ir_poll"]
        low, high = self.bounds(counts, count * byte, count + 1, wait)
        return (v | brr << 24) & 0xFFFFFFFF, low, high


def build(name: str, model: FreeRun, summary: str, blocks: tuple, question: str,
          source: str, observe: tuple, eeprom: bytes | None = None) -> Workload:
    return Workload(
        name=name, tier="hardware", summary=summary, blocks=blocks,
        evidence={"kind": "documented", "source": source, "question": question},
        image=model.image, horizons=HORIZONS, check=model.check, observe=observe,
        units=lambda h: {"cpu_states": h * PHI // 1000}, eeprom=eeprom, seed=model.seed)


def workloads(seed: int):
    yield build(
        "lcd-stream", LcdStream(seed),
        "Back-to-back raster blits to the NT7508 over the SSU at per-item clocks",
        ("cpu", "ssu", "lcd", "timer_w", "ports"),
        "Does every raster reach the right panel RAM, at no more than the SSU clock allows?",
        "REJ09B0152-0300 §15 (SSU, SSMR CKS), Table A.4; NT7508 data sheet (column, page and "
        "start-line commands)",
        ("ram", "lcd"))
    stream = EepromStream(seed)
    yield build(
        "eeprom-stream", stream,
        "Back-to-back M95512 page writes and reads over the SSU at per-item clocks",
        ("cpu", "ssu", "eeprom", "timer_w", "ports"),
        "Do page writes commit, reads return the stored bytes, and status polling see the "
        "write cycle end, at rates the SSU clock and the write time allow?",
        "REJ09B0152-0300 §15 (SSU), Table A.4; ST M95512 DS4192 (WREN, WRITE, READ, RDSR, "
        "page write, tW 5 ms)",
        ("ram", "eeprom"), eeprom=stream.initial)
    yield build(
        "ir-stream", IrStream(seed),
        "Back-to-back SCI3 IrDA transmit bursts at per-item bit rates, receiver enabled",
        ("cpu", "sci3", "timer_w"),
        "Does SCI3 transmit each burst at the rate BRR sets, double-buffered by TDRE and "
        "ending with TEND?",
        "REJ09B0152-0300 §14 (SCI3 asynchronous mode, BRR, TDRE/TEND, IrDA), Table A.4",
        ("ram",))
