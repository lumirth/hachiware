"""cpu: free-running compiled-code kernels, timed against Table A.4.

The guest never sleeps. It runs numbered work items back to back; item c
fills a buffer from a 16-bit LCG started at ``(c * MULT + ADD) mod 2^16``
(MULT and ADD come from the seed), then runs a CRC-16, an insertion sort and
hash, unsigned/signed word and byte multiply and divide, bit reversal with
BLD/BST and a bitmap with BSET Rn, a reversed long copy and a recursive
Fibonacci number, and folds the results into a 32-bit digest. Only instruction
forms of compiled retail firmware code are used.

Timer W counts phi/8 freely. At the end of each item the guest reads TCNT,
stores the digest and the counts since the previous item's read in a ring of
the last 16 items, and adds the counts to a 32-bit total. The check reads the
item count c from RAM and verifies, for the last 15 complete items:

- the digest, computed here from the kernels' definitions;
- the item's duration, which must equal the Table A.4 state count of the
  code the item executes (from the assembled listing, with execution counts
  of each basic block from the data) within the usual 8-state witness window;

and that c and the total are consistent with the observation time: the guest
cannot have completed more items, or fewer, than the documented clock allows.
A target that runs instructions in the wrong number of states, or runs Timer W
on a clock unrelated to the CPU, or completes work early, fails.
"""

from __future__ import annotations

import random
from functools import lru_cache

from ..freerun import HORIZONS, FreeRun
from ..runtime import PHI
from ..workload import Workload

M16, M32 = 0xFFFF, 0xFFFFFFFF

BODY = r"""
CRC = 0xf826
SORT = 0xf828
ACCB = 0xf82a
FIB = 0xf82c
REV = 0xf82e
TA = 0xf830
TB = 0xf832
ACCU = 0xf834
ACCS = 0xf838
COPYH = 0xf83c
COPYR = 0xf840
BITMAP = 0xf844
BUF = 0xfa00
BUF2 = 0xfc00

    mov.w #MULT, r1
    mulxu.w r1, er0
    add.w #ADD, r0
    ; K0: 128 words from a 16-bit linear congruential generator.
    mov.l #BUF, er2
    mov.w #128, r3
    mov.w #25173, r1
b_k0:
    mulxu.w r1, er0
    add.w #13849, r0
    mov.w r0, @er2
    adds #2, er2
    dec.w #1, r3
    bne b_k0
b_k1:
    ; K1: CRC-16/CCITT, MSB first, over the 256 bytes.
    mov.l #BUF, er2
    mov.w #256, r3
    mov.w #0xffff, r1
    mov.w #0x1021, r5
b_k1_byte:
    mov.b @er2+, r0l
    xor.b r0l, r1h
    mov.b #8, r0h
b_k1_bit:
    shll.w r1
    bcc b_k1_next
b_k1_xor:
    xor.w r5, r1
b_k1_next:
    dec.b r0h
    bne b_k1_bit
b_k1_byte_end:
    dec.w #1, r3
    bne b_k1_byte
b_k2:
    mov.w r1, @CRC
    ; K2: insertion sort of the first 64 words, then a rotate-xor hash.
    mov.l #BUF+2, er2
    mov.w #63, r6
b_k2_outer:
    mov.w @er2, r0
    mov.l er2, er3
b_k2_check:
    cmp.l #BUF, er3
    beq b_k2_place
b_k2_cmp:
    mov.w @(-2,er3), r1
    cmp.w r0, r1
    bls b_k2_place
b_k2_shift:
    mov.w r1, @er3
    subs #2, er3
    bra b_k2_check
b_k2_place:
    mov.w r0, @er3
    adds #2, er2
    dec.w #1, r6
    bne b_k2_outer
b_k2_hash:
    mov.l #BUF, er2
    mov.w #64, r6
    sub.w r1, r1
b_k2_hash_loop:
    mov.w @er2+, r0
    rotl.w r1
    xor.w r0, r1
    dec.w #1, r6
    bne b_k2_hash_loop
b_k3:
    mov.w r1, @SORT
    ; K3: unsigned, signed and byte multiply/divide over 32 word pairs.
    mov.l #BUF+128, er2
    mov.w #32, r6
    sub.l er4, er4
    sub.l er5, er5
    sub.w r3, r3
b_k3_loop:
    mov.w @er2+, r0
    mov.w r0, @TA
    mov.w @er2+, r1
    mov.w r1, @TB
    mulxu.w r1, er0
    mov.w @TA, r1
    or.w #1, r1
    divxu.w r1, er0
    mov.w e0, r1
    extu.l er1
    add.l er1, er4
    extu.l er0
    add.l er0, er4
    mov.w @TA, r0
    mov.w @TB, r1
    mulxs.w r1, er0
    add.l er0, er5
    mov.w @TA, r0
    shar.w r0
    exts.l er0
    mov.w @TB, r1
    shar.w r1
    shar.w r1
    shar.w r1
    shar.w r1
    shar.w r1
    shar.w r1
    shar.w r1
    shar.w r1
    or.w #1, r1
    divxs.w r1, er0
    mov.w e0, r1
    add.w r1, r0
    exts.l er0
    add.l er0, er5
    mov.w @TA, r0
    mov.w @TB, r1
    mov.b r1h, r1l
    mulxu.b r1l, r0
    mov.w @TA, r1
    or.b #1, r1l
    divxu.b r1l, r0
    add.b r0h, r0l
    mov.b r0l, r1l
    extu.w r1
    add.w r1, r3
    dec.w #1, r6
    bne b_k3_loop
b_k4:
    mov.l er4, @ACCU
    mov.l er5, @ACCS
    mov.w r3, @ACCB
    ; K4: bit reversal with BLD/BST and a bitmap set with BSET Rn,Rd.
    mov.l #BITMAP, er3
    sub.l er0, er0
    mov.l er0, @er3
    mov.l er0, @(4,er3)
    mov.b r0l, @REV
    mov.l #BUF, er2
    mov.w #128, r6
b_k4_loop:
    mov.b @er2+, r0l
    sub.b r1l, r1l
    bld #0, r0l
    bst #7, r1l
    bld #1, r0l
    bst #6, r1l
    bld #2, r0l
    bst #5, r1l
    bld #3, r0l
    bst #4, r1l
    bld #4, r0l
    bst #3, r1l
    bld #5, r0l
    bst #2, r1l
    bld #6, r0l
    bst #1, r1l
    bld #7, r0l
    bst #0, r1l
    mov.b @REV, r0h
    rotl.b r0h
    xor.b r1l, r0h
    mov.b r0h, @REV
    mov.b r0l, r1h
    shlr.b r1h
    shlr.b r1h
    shlr.b r1h
    and.b #7, r1h
    mov.b r0l, r1l
    and.b #7, r1l
    sub.l er3, er3
    mov.b r1h, r3l
    add.l #BITMAP, er3
    mov.b @er3, r0h
    bset r1l, r0h
    mov.b r0h, @er3
    dec.w #1, r6
    bne b_k4_loop
b_k5:
    ; K5: reversed long copy, then a forward pass over the copy.
    mov.l #BUF, er2
    mov.l #BUF2+256, er3
    mov.w #64, r6
    sub.l er4, er4
b_k5_copy:
    mov.l @er2+, er0
    mov.l er0, @-er3
    shll.l er4
    add.l er0, er4
    dec.w #1, r6
    bne b_k5_copy
b_k5_scan:
    mov.l er4, @COPYH
    mov.l #BUF2, er2
    mov.w #64, r6
    sub.l er5, er5
b_k5_scan_loop:
    mov.l @er2+, er0
    shlr.l er5
    xor.l er0, er5
    dec.w #1, r6
    bne b_k5_scan_loop
b_k6:
    mov.l er5, @COPYR
    ; K6: recursive Fibonacci of 10 + (c mod 4).
    mov.l @CUR, er0
    and.w #3, r0
    add.w #10, r0
    bsr fib:16
b_digest:
    mov.w r0, @FIB
    ; Digest: d = 2d + v over the results, modulo 2^32.
    sub.l er1, er1
    mov.w @CRC, r0
    extu.l er0
    shll.l er1
    add.l er0, er1
    mov.w @SORT, r0
    extu.l er0
    shll.l er1
    add.l er0, er1
    mov.l @ACCU, er0
    shll.l er1
    add.l er0, er1
    mov.l @ACCS, er0
    shll.l er1
    add.l er0, er1
    mov.w @ACCB, r0
    extu.l er0
    shll.l er1
    add.l er0, er1
    mov.b @REV, r0l
    extu.w r0
    extu.l er0
    shll.l er1
    add.l er0, er1
    mov.l @BITMAP, er0
    shll.l er1
    add.l er0, er1
    mov.l @BITMAP+4, er0
    shll.l er1
    add.l er0, er1
    mov.l @COPYH, er0
    shll.l er1
    add.l er0, er1
    mov.l @COPYR, er0
    shll.l er1
    add.l er0, er1
    mov.w @FIB, r0
    extu.l er0
    shll.l er1
    add.l er0, er1
"""

ROUTINES = r"""
b_fib:
fib:
    cmp.w #2, r0
    bcs b_fib_ret
b_fib_node:
    push.w r0
    dec.w #1, r0
    bsr fib
b_fib_mid:
    mov.w r0, r1
    pop.w r0
    push.w r1
    sub.w #2, r0
    bsr fib
b_fib_end:
    pop.w r1
    add.w r1, r0
b_fib_ret:
    rts
"""


def s16(x: int) -> int:
    x &= M16
    return x - 0x10000 if x & 0x8000 else x


def tdiv(a: int, b: int) -> tuple[int, int]:
    q = abs(a) // abs(b)
    if (a < 0) != (b < 0):
        q = -q
    return q, a - q * b


def fib_calls(n: int) -> tuple[int, int, int]:
    """(value, calls, calls with n >= 2) of the recursive guest routine."""
    if n < 2:
        return n, 1, 0
    a, ca, ia = fib_calls(n - 1)
    b, cb, ib = fib_calls(n - 2)
    return a + b, 1 + ca + cb, 1 + ia + ib


class Model(FreeRun):
    """Results and basic-block execution counts of one guest build."""

    def __init__(self, seed: int):
        rng = random.Random(f"cpu:{seed}")
        self.mult = rng.randrange(1, 0x10000, 2)
        self.add = rng.randrange(0x10000)
        body = BODY.replace("#MULT", f"#{self.mult}").replace("#ADD", f"#{self.add}")
        super().__init__(body, ROUTINES, seed)

    @lru_cache(maxsize=4096)
    def item(self, c: int) -> tuple[int, int]:
        """(digest, states, states) of item c: its CPU work is exactly timed."""
        n = {"b_k0": 128, "b_k1": 1, "b_k1_byte": 256,
             "b_k1_bit": 2048, "b_k1_next": 2048, "b_k1_byte_end": 256, "b_k2": 1,
             "b_k2_outer": 63, "b_k2_place": 63, "b_k2_hash": 1, "b_k2_hash_loop": 64,
             "b_k3": 1, "b_k3_loop": 32, "b_k4": 1, "b_k4_loop": 128, "b_k5": 1,
             "b_k5_copy": 64, "b_k5_scan": 1, "b_k5_scan_loop": 64, "b_k6": 1,
             "b_digest": 1}
        x = (c * self.mult + self.add) & M16
        words = []
        for _ in range(128):
            x = (x * 25173 + 13849) & M16
            words.append(x)
        data = b"".join(w.to_bytes(2, "big") for w in words)
        crc, xors = 0xFFFF, 0
        for byte in data:
            crc ^= byte << 8
            for _ in range(8):
                if crc & 0x8000:
                    crc = ((crc << 1) ^ 0x1021) & M16
                    xors += 1
                else:
                    crc = (crc << 1) & M16
        n["b_k1_xor"] = xors
        checks = compares = shifts = 0
        prefix = words[:64]
        for i in range(1, 64):
            v, j = prefix[i], i
            while j > 0 and prefix[j - 1] > v:
                prefix[j] = prefix[j - 1]
                j -= 1
            moved = i - j
            shifts += moved
            checks += moved + 1
            compares += moved + (1 if j > 0 else 0)
            prefix[j] = v
        words[:64] = prefix
        n.update(b_k2_check=checks, b_k2_cmp=compares, b_k2_shift=shifts)
        sort = 0
        for w in words[:64]:
            sort = (((sort << 1) | (sort >> 15)) & M16) ^ w
        accu = accs = accb = 0
        for j in range(32):
            a, b = words[64 + 2 * j], words[65 + 2 * j]
            q, r = divmod(a * b, a | 1)
            accu = (accu + q + r) & M32
            accs = (accs + s16(a) * s16(b)) & M32
            q, r = tdiv(s16(a) >> 1, (s16(b) >> 8) | 1)
            accs = (accs + s16(q + r)) & M32
            q, r = divmod((a & 0xFF) * (b >> 8), (a & 0xFF) | 1)
            accb = (accb + ((q + r) & 0xFF)) & M16
        data = b"".join(w.to_bytes(2, "big") for w in words)
        rev, bitmap = 0, bytearray(8)
        for byte in data[:128]:
            r = int(f"{byte:08b}"[::-1], 2)
            rev = (((rev << 1) | (rev >> 7)) & 0xFF) ^ r
            bitmap[(byte >> 3) & 7] |= 1 << (byte & 7)
        longs = [int.from_bytes(data[4 * i:4 * i + 4], "big") for i in range(64)]
        copyh = 0
        for v in longs:
            copyh = ((copyh << 1) + v) & M32
        copyr = 0
        for v in reversed(longs):
            copyr = (copyr >> 1) ^ v
        fib, calls, nodes = fib_calls(10 + (c & 3))
        n.update(b_fib=calls, b_fib_ret=calls, b_fib_node=nodes, b_fib_mid=nodes,
                 b_fib_end=nodes)
        digest = 0
        for v in (crc, sort, accu, accs, accb, rev, int.from_bytes(bitmap[:4], "big"),
                  int.from_bytes(bitmap[4:], "big"), copyh, copyr, fib):
            digest = ((digest << 1) + v) & M32
        states = self.states(n)
        return digest, states, states


def workloads(seed: int):
    model = Model(seed)
    yield Workload(
        name="cpu",
        tier="hardware",
        summary="Free-running compiled-code kernels (CRC, sort, multiply/divide, bit "
                "operations, copies, recursion) with every item's duration timed",
        blocks=("cpu", "cpu_timing", "timer_w", "watchdog"),
        evidence={
            "kind": "documented",
            "source": "REJ09B0153 (H8/300H software manual) instruction definitions; "
                      "REJ09B0152-0300 Appendix A.3 and Table A.4 (state counts), §20.1 "
                      "(register access states), §10 (Timer W free-running at phi/8)",
            "question": "Do back-to-back kernels compute the results their instruction "
                        "definitions give, each in the documented number of states, with "
                        "as many items completed as the clock allows?",
        },
        image=model.image,
        horizons=HORIZONS,
        check=model.check,
        observe=("ram",),
        units=lambda h: {"cpu_states": h * PHI // 1000},
        seed=seed,
    )
