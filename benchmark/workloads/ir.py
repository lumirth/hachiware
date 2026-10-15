"""IR sync: a game exchanging EEPROM pages with the walker, back to back.

The walker runs the retail IR loop shape (lumirth/pw IrConfigure,
IrHardwareStart, IrProtocolTick, SendPacket, PacketChecksum): SCI3 in IrDA
mode at 115200 bit/s with receiver and transmitter enabled, polled in active
high-speed mode with the watchdog serviced and SSR3 cleared on every pass,
bytes XORed with 0xAA, a packet closed by a Timer W (phiW) idle gap. The idle
gap is 8 phiW ticks rather than the firmware's 4 so that the result does not
depend on the phase of the tick.

Each exchange period carries two packets from the game:

- a 136-byte write packet: the walker verifies the checksum, writes the
  128-byte payload to an EEPROM page and acknowledges, or answers a corrupted
  packet with a negative acknowledgement and no write;
- an 8-byte read request: the walker reads the requested page from EEPROM and
  replies with a 136-byte packet, or answers a corrupted request with a
  negative acknowledgement.

The game is an open-loop peer with a documented turnaround: each packet starts
a fixed time after the latest instant a correct walker can have finished its
previous reply (bits on the wire at 115200 bit/s, generously bounded CPU work
and the M95512's 5 ms maximum write time). A walker that runs late in emulated
time loses bytes and fails its checksums. The walker times each of its own
transmissions from the first TDR3 write to TEND with Timer W and keeps the
shortest and longest of each kind; a walker that transmits at the wrong rate
fails those witnesses. A running sum of reply checksums shows that every
reply carried the EEPROM contents. Payloads, pages, corruption and the
initial EEPROM contents come from the seed.

"""

from __future__ import annotations

import random

from ..runtime import PHI, PHI_W, RESULTS, program
from ..workload import Paced, Workload, u16

BIT_US = 32 * 1_000_000 / PHI  # BRR3 = 0, SMR3 = 0: phi/32 per bit.
XOR = 0xAA
TOKEN = bytes((0x12, 0x34, 0x56, 0x78))
WRITE, ACK, NAK, READ, REPLY = 0x02, 0x04, 0x06, 0x0C, 0x0E
BASE = 0x6000
PAGES = 64
PAYLOAD = 128
# Exchange k starts at SETUP + PERIOD * (k - 1) + LEAD ms; its read request
# follows at READ_AT ms. Latest walker completion, from the documented rates:
# write packet 13.0 ms on the wire, idle gap <= 0.3 ms, checksum and page write
# over the SSU at phi/4 <= 4 ms, ACK 0.7 ms: done by 18 ms, so the request
# at 24 ms leaves the game 6 ms of turnaround. Request 0.8 ms, gap 0.3 ms,
# write cycle (<= 5 ms after the page write) and page read <= 4 ms, checksum
# <= 1 ms, reply 11.8 ms: done by 43 ms, inside the 48 ms between the
# exchange start and the observation.
PERIOD, SETUP, LEAD, READ_AT = 50, 31, 27, 24
STATES_PER_TICK = PHI / PHI_W
BYTE_STATES = 10 * 32  # 8N1 at 32 states per bit.
# Transmit timing: from the TCNT read before the first TDR3 write to the read
# after TEND. At least the bits on the wire; at most one bit of start-up
# latency and the polling and read instructions on top. One tick either way
# for sampling a tick counter at both ends.
TX_SLACK_STATES = 32 + 64

GUEST = r"""
BUF = 0xfa00
COUNT = 0xf820
LAST = 0xf822
DRAIN = 0xf824
R_WOK = 0xf780
R_WBAD = 0xf782
R_WSUM = 0xf784
R_ROK = 0xf786
R_RBAD = 0xf788
R_RSUM = 0xf78a
R_PACKETS = 0xf78c
R_SHORT_MIN = 0xf78e
R_SHORT_MAX = 0xf790
R_LONG_MIN = 0xf792
R_LONG_MAX = 0xf794
GAP = 8

    jsr @wdt_start
    jsr @hw_setup
    sub.w r0, r0
    mov.w r0, @COUNT
    mov.w #0xffff, r0
    mov.w r0, @R_SHORT_MIN
    mov.w r0, @R_LONG_MIN
    ; IrInitPins and IrConfigure.
    mov.b #3, r0l
    mov.b r0l, @0xf088
    mov.b #1, r0l
    mov.b r0l, @0xffd6
    mov.b #5, r0l
    mov.b r0l, @0xffe6
    bset #6, @CKSTPR1:8
    mov.b #1, r0l
    mov.b r0l, @SPCR
    mov.b @SSR3, r0l
    and.b #0x84, r0l
    mov.b r0l, @SSR3
    sub.b r0l, r0l
    mov.b r0l, @SEMR
    mov.b r0l, @SCR3
    mov.b r0l, @SMR3
    mov.b r0l, @BRR3
    mov.b #5, r0l
1:  dec.b r0l
    bne 1b
    mov.b #0x10, r0l
    mov.b r0l, @SCR3
    mov.b #0x80, r0l
    mov.b r0l, @IRCR
    mov.b #0x11, r0l
    mov.b r0l, @SPCR
    mov.b #0x30, r0l
    mov.b r0l, @SCR3
    sub.b r0l, r0l
    mov.b r0l, @0xffd6
    ; IrHardwareStart: Timer W free-running on phiW as the protocol clock.
    bset #6, @CKSTPR2:8
    mov.b @TCRW, r0l
    and.b #0x8f, r0l
    or.b #0x40, r0l
    and.b #0x7f, r0l
    mov.b r0l, @TCRW
    mov.b @TIERW, r0l
    and.b #0xfe, r0l
    mov.b r0l, @TIERW
    mov.b #0x80, r0l
    mov.b r0l, @TMRW
    mov.b @SSR3, r0l
    and.b #0xc4, r0l
    mov.b r0l, @SSR3
    mov.b @SSR3, r0l
    btst #6, r0l
    beq main
    mov.b @RDR3, r0l
; IrProtocolTick, called back to back as the retail task loop does.
main:
    jsr @wdt_kick
    mov.b @SSR3, r0l
    and.b #0xc4, r0l
    mov.b r0l, @SSR3
    btst #6, r0l
    beq 2f
    mov.b @RDR3, r0l
    xor.b #0xaa, r0l
    mov.w @COUNT, r1
    cmp.w #136, r1
    bcc 1f
    mov.l #BUF, er2
    add.w r1, r2
    mov.b r0l, @er2
1:  inc.w #1, r1
    mov.w r1, @COUNT
    mov.w @TCNT, r0
    mov.w r0, @LAST
    bra main
2:  mov.w @COUNT, r1
    beq main
    mov.w @TCNT, r0
    mov.w @LAST, r1
    sub.w r1, r0
    cmp.w #GAP, r0
    bcs main
    jsr @packet
    sub.w r0, r0
    mov.w r0, @COUNT
    bra main

; PacketChecksum: big-endian words of r3 bytes (even) at er2, seeded with 2,
; folded. Result in r0.
checksum:
    mov.l #2, er4
1:  mov.w @er2+, r0
    extu.l er0
    add.l er0, er4
    subs #2, er3
    mov.l er3, er3
    bne 1b
    mov.w e4, r1
    extu.l er1
    mov.w r4, r0
    extu.l er0
    add.l er1, er0
    mov.w e0, r1
    add.w r1, r0
    rts

; Verify the received checksum over r3 bytes (the header carries it low
; byte first). Z set when it matches; r0 holds the computed value.
verify:
    mov.w @BUF + 2, r5
    sub.w r0, r0
    mov.w r0, @BUF + 2
    mov.l #BUF, er2
    jsr @checksum
    mov.b r0h, r1l
    mov.b r0l, r1h
    cmp.w r1, r5
    rts

; Seal the packet of r3 bytes at BUF with its checksum; r0 holds it.
seal:
    sub.w r0, r0
    mov.w r0, @BUF + 2
    mov.l #BUF, er2
    jsr @checksum
    mov.b r0l, @BUF + 2
    mov.b r0h, @BUF + 3
    rts

; EEPROM address of the page named by the argument byte, in r1.
page:
    mov.b @BUF + 1, r1l
    and.b #63, r1l
    sub.b r1h, r1h
    shll.w r1
    shll.w r1
    shll.w r1
    shll.w r1
    shll.w r1
    shll.w r1
    shll.w r1
    add.w #BASE, r1
    rts

packet:
    mov.w @R_PACKETS, r0
    inc.w #1, r0
    mov.w r0, @R_PACKETS
    mov.w @COUNT, r0
    cmp.w #136, r0
    bne 5f
    ; Write packet.
    mov.b @BUF, r0l
    cmp.b #WRITE, r0l
    bne 4f
    mov.l #136, er3
    jsr @verify
    bne 4f
    mov.w r0, @R_WSUM
    jsr @page
    mov.l #BUF + 8, er2
    mov.w #128, r3
    jsr @eep_write
    mov.w @R_WOK, r0
    inc.w #1, r0
    mov.w r0, @R_WOK
    mov.b #ACK, r0l
    bra 8f
4:  mov.w @R_WBAD, r0
    inc.w #1, r0
    mov.w r0, @R_WBAD
    mov.b #NAK, r0l
    bra 8f
5:  ; Read request.
    cmp.w #8, r0
    bne 6f
    mov.b @BUF, r0l
    cmp.b #READ, r0l
    bne 6f
    mov.l #8, er3
    jsr @verify
    bne 6f
    jsr @page
    mov.l #BUF + 8, er2
    mov.w #128, r3
    jsr @eep_read
    mov.b #REPLY, r0l
    mov.b r0l, @BUF
    mov.l #136, er3
    jsr @seal
    mov.w @R_RSUM, r1
    add.w r0, r1
    mov.w r1, @R_RSUM
    mov.w @R_ROK, r0
    inc.w #1, r0
    mov.w r0, @R_ROK
    mov.b #136, r3l
    jsr @send
    mov.l #R_LONG_MIN, er2
    bra record
6:  mov.w @R_RBAD, r0
    inc.w #1, r0
    mov.w r0, @R_RBAD
    mov.b #NAK, r0l
8:  ; Short reply: command, argument, checksum, the received token.
    mov.b r0l, @BUF
    mov.l #8, er3
    jsr @seal
    mov.b #8, r3l
    jsr @send
    mov.l #R_SHORT_MIN, er2
; Keep the shortest and longest transmit duration (r0) at @er2 and @(2,er2).
record:
    mov.w @er2, r1
    cmp.w r1, r0
    bcc 1f
    mov.w r0, @er2
1:  mov.w @(2,er2), r1
    cmp.w r1, r0
    bls 2f
    mov.w r0, @(2,er2)
2:  rts

; SendPacket: transmit r3l bytes from BUF, XORed, as TDRE allows; wait for
; TEND and two Timer W counts, drain a pending receive byte. Returns the
; Timer W counts from before the first TDR3 write to TEND in r0.
send:
    mov.l #BUF, er2
1:  mov.b @SSR3, r0h
    btst #7, r0h
    beq 1b
    mov.w @TCNT, r6
    bra 3f
2:  mov.b @SSR3, r0h
    btst #7, r0h
    beq 2b
3:  mov.b @er2+, r0l
    xor.b #0xaa, r0l
    mov.b r0l, @TDR3
    dec.b r3l
    bne 2b
4:  mov.b @SSR3, r0l
    btst #2, r0l
    beq 4b
    mov.w @TCNT, r5
    sub.w r6, r5
    mov.w @TCNT, r1
5:  mov.w @TCNT, r0
    sub.w r1, r0
    cmp.w #2, r0
    bcs 5b
    mov.b @SSR3, r0l
    btst #6, r0l
    beq 6f
    mov.b @RDR3, r0l
    mov.b r0l, @DRAIN
6:  mov.w r5, r0
    rts
"""


def checksum(data: bytes) -> int:
    total = 2
    for i, value in enumerate(data):
        total += value << 8 if i % 2 == 0 else value
    total = (total >> 16) + (total & 0xFFFF)
    total += total >> 16
    return total & 0xFFFF


def frame(command: int, argument: int, payload: bytes) -> bytes:
    body = bytes((command, argument, 0, 0)) + TOKEN + payload
    value = checksum(body)
    return body[:2] + bytes((value & 0xFF, value >> 8)) + body[4:]


def exchange(seed: int, k: int) -> tuple[bytes, bool, bytes, bool]:
    """Exchange k (from 1): write packet, whether intact, read request, whether intact."""
    rng = random.Random(f"ir-sync:{seed}:{k}")
    payload = bytes(rng.randrange(256) for _ in range(PAYLOAD))
    write = bytearray(frame(WRITE, rng.randrange(PAGES), payload))
    write_ok = rng.randrange(8) != 0
    if not write_ok:
        write[8 + rng.randrange(PAYLOAD)] ^= 1 << rng.randrange(8)
    request = bytearray(frame(READ, rng.randrange(PAGES), b""))
    request_ok = rng.randrange(16) != 0
    if not request_ok:
        request[4 + rng.randrange(4)] ^= 1 << rng.randrange(8)
    return bytes(write), write_ok, bytes(request), request_ok


def initial_eeprom(seed: int) -> bytes:
    rng = random.Random(f"ir-sync-eeprom:{seed}")
    image = bytearray(b"\xff" * 65536)
    image[BASE:BASE + PAGES * PAYLOAD] = bytes(rng.randrange(256)
                                               for _ in range(PAGES * PAYLOAD))
    return bytes(image)


def pulses(data: bytes, start_us: float) -> list[str]:
    rows = []
    for j, value in enumerate(data):
        wire = value ^ XOR
        bits = [0] + [wire >> i & 1 for i in range(8)]
        for i, bit in enumerate(bits):
            if not bit:
                at = round(start_us + (j * 11 + i) * BIT_US)
                rows += [f"{at},ir,1", f"{at + 2},ir,0"]
    return rows


def timeline(seed: int, milliseconds: int) -> str:
    rows = []
    k = 1
    while True:
        start_us = (SETUP + PERIOD * (k - 1) + LEAD) * 1000
        if start_us > milliseconds * 1000:
            break
        write, _, request, _ = exchange(seed, k)
        rows += pulses(write, start_us)
        rows += pulses(request, start_us + READ_AT * 1000)
        k += 1
    return "\n".join(rows) + "\n"


def tx_window(count: int) -> tuple[int, int]:
    low = count * BYTE_STATES
    high = low + TX_SLACK_STATES
    return int(low // STATES_PER_TICK) - 1, -int(-high // STATES_PER_TICK) + 1


def workload(seed: int) -> Workload:
    source = GUEST
    for name, value in (("#WRITE", WRITE), ("#ACK", ACK), ("#NAK", NAK), ("#READ", READ),
                        ("#REPLY", REPLY), ("#BASE", BASE)):
        source = source.replace(name, f"#{value:#x}")
    image, _symbols = program(source, {}, seed=seed)
    initial = initial_eeprom(seed)

    def model(n: int) -> dict:
        pages = {p: initial[BASE + PAYLOAD * p:BASE + PAYLOAD * (p + 1)] for p in range(PAGES)}
        state = dict(wok=0, wbad=0, wsum=0, rok=0, rbad=0, rsum=0)
        for k in range(1, n + 1):
            write, write_ok, request, request_ok = exchange(seed, k)
            if write_ok:
                state["wok"] += 1
                pages[write[1]] = write[8:]
                state["wsum"] = checksum(write[:2] + b"\0\0" + write[4:])
            else:
                state["wbad"] += 1
            if request_ok:
                state["rok"] += 1
                reply = bytes((REPLY, request[1], 0, 0)) + TOKEN + pages[request[1]]
                state["rsum"] = (state["rsum"] + checksum(reply)) & 0xFFFF
            else:
                state["rbad"] += 1
        state["pages"] = pages
        return state

    def expected(n: int) -> dict:
        s = model(n)
        ram = {"f7fc": "00000000"}
        ram[f"{RESULTS:04x}"] = "".join(u16(v) for v in (
            s["wok"], s["wbad"], s["wsum"], s["rok"], s["rbad"], s["rsum"], 2 * n))
        return {"ram": ram, "eeprom": {f"{BASE + PAYLOAD * p:04x}": data.hex()
                                       for p, data in sorted(s["pages"].items())}}

    def witnesses(n: int) -> dict:
        if not n:
            return {}
        s = model(n)
        low, high = tx_window(8)
        out = {"short_tx_shortest": (RESULTS + 14, 2, low, high),
               "short_tx_longest": (RESULTS + 16, 2, low, high)}
        if s["rok"]:
            low, high = tx_window(8 + PAYLOAD)
            out |= {"reply_tx_shortest": (RESULTS + 18, 2, low, high),
                    "reply_tx_longest": (RESULTS + 20, 2, low, high)}
        return out

    paced = Paced(PERIOD, SETUP, (1, 3, 7, 15, 31, 63, 127, 255, 511, 1023), expected,
                  witnesses, units=lambda n: {"exchanges": n})
    return Workload(
        name="ir-sync",
        tier="use",
        summary="IR sync: back-to-back 136-byte EEPROM page writes and page reads with "
                "the game over IrDA at 115200 bit/s, verified, stored, read back, "
                "acknowledged and answered, every transmission timed",
        blocks=("cpu", "sci3", "timer_w", "ssu", "eeprom", "watchdog"),
        image=image, seed=seed, eeprom=initial,
        observe=("eeprom", "ram"),
        timeline=lambda ms: timeline(seed, ms),
        inputs=("ir",),
        evidence={
            "kind": "software_reasoned",
            "source": "lumirth/pw IrConfigure, IrHardwareStart, IrProtocolTick, SendPacket, "
                      "PacketChecksum, IrTransmitByte (XOR 0xAA), EepromRead, EepromWrite; "
                      "REJ09B0152-0300 §14 (SCI3 asynchronous mode, IrDA, TDRE/TEND), §10 "
                      "(Timer W on phiW); ST M95512 DS4192 (page write, tW 5 ms)",
            "question": "Does a polled IrDA sync receive every byte, store and read back "
                        "EEPROM pages, and transmit every acknowledgement and reply at the "
                        "configured bit rate in time for the game's next packet?",
        },
        **paced.fields(),
    )



# --- ir-probe: connection probing and retries ---------------------------------
# PROBE_PERIOD ms per connection: the walker transmits a CONNECT probe and polls
# the IrProtocolTick loop (watchdog serviced, SSR3 cleared on every pass),
# retransmitting CONNECT every PROBE_TIMEOUT Timer W ticks until a peer answers.
# The peer answers once per period, PROBE_OFFSET ms in, chosen past the pass
# midpoint-minus-period so exactly n answers land by the n-th midpoint. On an
# answer the walker sends an 8-byte response, whose transmit is timed. The retry
# spin executes in the guest. The answer count, checksum, and transmit duration
# witness completed exchanges independently of the number of retries.
PROBE_PERIOD, PROBE_SETUP, PROBE_OFFSET, PROBE_TIMEOUT = 100, 31, 70, 312
CONNECT = 0xFC

PROBE_GUEST = r"""
BUF = 0xfa00
R_SESSIONS = 0xf780
R_RSUM = 0xf782
R_SHORT_MIN = 0xf784
R_SHORT_MAX = 0xf786

    jsr @wdt_start
    jsr @hw_setup
    sub.w r0, r0
    mov.w r0, @R_SESSIONS
    mov.w r0, @R_RSUM
    mov.w r0, @R_SHORT_MAX
    mov.l #BUF, er2
    mov.b #8, r3l
1:  sub.b r0l, r0l
    mov.b r0l, @er2
    adds #1, er2
    dec.b r3l
    bne 1b
    mov.w #0xffff, r0
    mov.w r0, @R_SHORT_MIN
    ; IrInitPins and IrConfigure.
    mov.b #3, r0l
    mov.b r0l, @0xf088
    mov.b #1, r0l
    mov.b r0l, @0xffd6
    mov.b #5, r0l
    mov.b r0l, @0xffe6
    bset #6, @CKSTPR1:8
    mov.b #1, r0l
    mov.b r0l, @SPCR
    mov.b @SSR3, r0l
    and.b #0x84, r0l
    mov.b r0l, @SSR3
    sub.b r0l, r0l
    mov.b r0l, @SEMR
    mov.b r0l, @SCR3
    mov.b r0l, @SMR3
    mov.b r0l, @BRR3
    mov.b #5, r0l
1:  dec.b r0l
    bne 1b
    mov.b #0x10, r0l
    mov.b r0l, @SCR3
    mov.b #0x80, r0l
    mov.b r0l, @IRCR
    mov.b #0x11, r0l
    mov.b r0l, @SPCR
    mov.b #0x30, r0l
    mov.b r0l, @SCR3
    sub.b r0l, r0l
    mov.b r0l, @0xffd6
    ; IrHardwareStart: Timer W free-running on phiW as the protocol clock.
    bset #6, @CKSTPR2:8
    mov.b @TCRW, r0l
    and.b #0x8f, r0l
    or.b #0x40, r0l
    and.b #0x7f, r0l
    mov.b r0l, @TCRW
    mov.b @TIERW, r0l
    and.b #0xfe, r0l
    mov.b r0l, @TIERW
    mov.b #0x80, r0l
    mov.b r0l, @TMRW
    mov.b @SSR3, r0l
    and.b #0xc4, r0l
    mov.b r0l, @SSR3
    mov.b @SSR3, r0l
    btst #6, r0l
    beq session
    mov.b @RDR3, r0l

; Probe for a peer: send CONNECT, poll, retransmit on timeout, answer the reply.
session:
    jsr @tx_connect
    mov.w @TCNT, r6
poll:
    jsr @wdt_kick
    mov.b @SSR3, r0l
    and.b #0xc4, r0l
    mov.b r0l, @SSR3
    btst #6, r0l
    bne answered
    mov.w @TCNT, r0
    sub.w r6, r0
    cmp.w #TIMEOUT, r0
    blo poll
    jsr @tx_connect
    mov.w @TCNT, r6
    bra poll
answered:
    mov.b @RDR3, r0l
    xor.b #0xaa, r0l
    sub.b r0h, r0h
    mov.w @R_RSUM, r1
    add.w r0, r1
    mov.w r1, @R_RSUM
    jsr @send_response
    mov.w @R_SESSIONS, r0
    inc.w #1, r0
    mov.w r0, @R_SESSIONS
    bra session

; Transmit one CONNECT byte, wait for the end of transmission and drain the
; half-duplex echo of our own byte so it is not mistaken for a peer answer.
tx_connect:
    mov.b @SSR3, r0h
    btst #7, r0h
    beq tx_connect
    mov.b #0xfc, r0l
    xor.b #0xaa, r0l
    mov.b r0l, @TDR3
1:  mov.b @SSR3, r0l
    btst #2, r0l
    beq 1b
    mov.b @SSR3, r0l
    btst #6, r0l
    beq 2f
    mov.b @RDR3, r0l
2:  rts

; Send the 8-byte response from BUF, timing it from the TCNT read before the
; first TDR3 write to the read after TEND, and drain the echo. Records min/max.
send_response:
    mov.l #BUF, er2
    mov.b #8, r3l
1:  mov.b @SSR3, r0h
    btst #7, r0h
    beq 1b
    mov.w @TCNT, r6
    bra 3f
2:  mov.b @SSR3, r0h
    btst #7, r0h
    beq 2b
3:  mov.b @er2+, r0l
    xor.b #0xaa, r0l
    mov.b r0l, @TDR3
    dec.b r3l
    bne 2b
4:  mov.b @SSR3, r0l
    btst #2, r0l
    beq 4b
    mov.w @TCNT, r5
    sub.w r6, r5
    mov.b @SSR3, r0l
    btst #6, r0l
    beq 5f
    mov.b @RDR3, r0l
5:  mov.w @R_SHORT_MIN, r1
    cmp.w r1, r5
    bcc 6f
    mov.w r5, @R_SHORT_MIN
6:  mov.w @R_SHORT_MAX, r1
    cmp.w r1, r5
    bls 7f
    mov.w r5, @R_SHORT_MAX
7:  rts
"""


def probe_byte(seed: int, k: int) -> int:
    return random.Random(f"ir-probe:{seed}:{k}").randrange(256)


def probe_timeline(seed: int, milliseconds: int) -> str:
    rows = []
    k = 1
    while True:
        at = (PROBE_SETUP + PROBE_PERIOD * (k - 1) + PROBE_OFFSET) * 1000
        if at > milliseconds * 1000:
            break
        rows += pulses(bytes((probe_byte(seed, k),)), at)
        k += 1
    return "\n".join(rows) + "\n"


def probe_workload(seed: int) -> Workload:
    source = PROBE_GUEST.replace("#TIMEOUT", f"#{PROBE_TIMEOUT}")
    image, _symbols = program(source, {}, seed=seed)

    def expected(n: int) -> dict:
        rsum = sum(probe_byte(seed, k) for k in range(1, n + 1)) & 0xFFFF
        return {"ram": {"f7fc": "00000000",
                        f"{RESULTS:04x}": u16(n) + u16(rsum)}}

    def witnesses(n: int) -> dict:
        if not n:
            return {}
        low, high = tx_window(8)
        return {"response_tx_shortest": (RESULTS + 4, 2, low, high),
                "response_tx_longest": (RESULTS + 6, 2, low, high)}

    paced = Paced(PROBE_PERIOD, PROBE_SETUP, (1, 3, 7, 15, 31, 63, 127, 255, 511),
                  expected, witnesses, units=lambda n: {"connections": n})
    return Workload(
        name="ir-probe",
        tier="use",
        summary="IR connection probing: CONNECT probes retransmitted on timeout until a peer "
                "answers each period, every answer counted, folded and responded to, the "
                "response transmit timed",
        blocks=("cpu", "sci3", "timer_w", "watchdog"),
        image=image, seed=seed,
        observe=("ram",),
        timeline=lambda ms: probe_timeline(seed, ms),
        inputs=("ir",),
        evidence={
            "kind": "software_reasoned",
            "source": "lumirth/pw IrBegin, IrConfigure, IrHardwareStart, IrProtocolTick "
                      "(WatchdogService, SSR3 clear, CONNECT retransmit on PW_IR_INACTIVITY_TICKS "
                      "timeout), SendPacket; REJ09B0152-0300 §14 (SCI3 IrDA), §10 (Timer W)",
            "question": "Does the probe loop keep retransmitting CONNECT until a peer answers, "
                        "then read each answer and transmit a response at the configured bit "
                        "rate?",
        },
        **paced.fields(),
    )


def workloads(seed: int):
    yield workload(seed)
    yield probe_workload(seed)
