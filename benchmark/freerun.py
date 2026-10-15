"""Free-running guests: numbered work items back to back, timed by Timer W.

A free-running guest never waits for a time base. Item c (from 1) runs the
workload's body, which leaves a 32-bit digest of the item in er1. The shared
epilogue reads Timer W (counting phi/8 from the start and never cleared),
stores the digest and the phi/8 counts since the previous item's read in slot
``c mod 16`` of a ring at RING, adds the counts to a 32-bit total and only
then stores the item count. An observation can stop the guest anywhere, so
items c-14..c are complete and consistent while item c+1 may be partial.

Each item has documented bounds on its duration in states: exact for pure
CPU work (Table A.4 over the basic blocks the item executes), and for device
traffic at least the bits a serial line must carry at its configured clock
and at most that plus all of the item's CPU work done serially. The check
verifies each recent item's digest and duration, and that the item count and
total fit the observation time: the work cannot finish earlier or later than
the documented clocks allow.

Bodies label their basic blocks ``b_<name>``; a block runs to the next such
label. ``Model.counts(c)`` gives each block's executions for item c; the
helper adds the shared item entry and epilogue.
"""

from __future__ import annotations

from cases import timing

from .runtime import PHI, program
from .witness import WINDOW_STATES
from .workload import read

COUNT, TOTAL, RING, SLOTS = 0xF780, 0xF784, 0xF880, 16

PROLOGUE = r"""
COUNT = 0xf780
TOTAL = 0xf784
CUR = 0xf820
PREV = 0xf824
RING = 0xf880

    jsr @wdt_start
    sub.l er0, er0
    mov.l er0, @COUNT
    mov.l er0, @TOTAL
    ; Timer W counts phi/8 and is never cleared.
    bset #6, @CKSTPR2:8
    sub.b r0l, r0l
    mov.b r0l, @TMRW
    mov.b r0l, @TIERW
    mov.b #0x30, r0l
    mov.b r0l, @TCRW
    sub.w r0, r0
    mov.w r0, @TCNT
    mov.b #0x80, r0l
    mov.b r0l, @TMRW
    mov.w @TCNT, r0
first_read:
    mov.w r0, @PREV
    ; Device set-up runs inside item 1, whose duration is not checked.
SETUP
b_item:
    jsr @wdt_kick
    mov.l @COUNT, er0
    inc.l #1, er0
    mov.l er0, @CUR
"""

EPILOGUE = r"""
b_ring:
    ; Ring slot c mod 16: digest, then phi/8 counts since the previous item.
    mov.l @CUR, er0
    mov.b r0l, r2l
    and.b #15, r2l
    shll.b r2l
    shll.b r2l
    shll.b r2l
    sub.l er3, er3
    mov.b r2l, r3l
    add.l #RING, er3
    mov.l er1, @er3
    mov.w @TCNT, r4
    mov.w @PREV, r5
    mov.w r4, @PREV
    sub.w r5, r4
    mov.w r4, @(4,er3)
    extu.l er4
    mov.l @TOTAL, er5
    add.l er4, er5
    mov.l er5, @TOTAL
    mov.l er0, @COUNT
    jmp @b_item
"""


class FreeRun:
    """Assembled free-running guest with its block state counts.

    ``item(c)`` must return (digest, low states, high states) for item c;
    ``extra(c, observed)`` returns failures of other memory after c items.
    """

    def __init__(self, body: str, routines: str, seed: int, handlers: dict | None = None,
                 setup: str = ""):
        from cases.asm import Listing

        listing, symbols = Listing(), {}
        source = (PROLOGUE.replace("SETUP", setup) + body + EPILOGUE + routines
                  + "\nb_end:\n")
        self.image, self.symbols = program(source, handlers or {}, symbols=symbols,
                                           listing=listing, seed=seed)
        self.listing = listing
        labels = sorted((a, n) for n, a in self.symbols.items() if n.startswith("b_"))
        self.block = {}
        for (start, name), (end, _next) in zip(labels, labels[1:]):
            self.block[name] = timing.span(listing, start, end)
        self.block["wdt_kick"] = timing.span(listing, self.symbols["wdt_kick"],
                                             self.symbols["hw_setup"])
        read_entry = next(e for e in listing if e[0] + e[3] == self.symbols["first_read"])
        # States from the first instruction to the first TCNT sample. Reset
        # exception handling before it only moves the observation later.
        states = timing.span(listing, self.symbols["start"], read_entry[0])
        states += timing.span(listing, self.symbols["wdt_start"], self.symbols["wdt_kick"])
        states += timing.states(read_entry) - timing.access_states(0xF0F6, 2)
        self.setup_states = states + self.setup_extra()

    def setup_extra(self) -> int:
        """States of setup code outside the prologue span (called routines)."""
        return 0

    def states(self, counts: dict) -> int:
        """CPU states of one item with the given block execution counts."""
        counts = {"b_item": 1, "wdt_kick": 1, "b_ring": 1, **counts}
        missing = set(self.block) - set(counts) - {"b_end"}
        unknown = set(counts) - set(self.block)
        if missing or unknown:
            raise ValueError(f"block counts missing {sorted(missing)}, unknown {sorted(unknown)}")
        return sum(self.block[name] * count for name, count in counts.items())

    def item(self, c: int) -> tuple[int | None, int, int]:
        raise NotImplementedError

    def extra(self, c: int, observed: dict) -> list[str]:
        return []

    def check(self, horizon: int, observed: dict) -> list[str]:
        failures = []
        if read(observed, 0xF7FC, 4):
            failures.append("unexpected interrupt entries recorded at f7fc")
        c, total = read(observed, COUNT, 4), read(observed, TOTAL, 4)
        if c < 2:
            return failures + [f"only {c} items completed in {horizon} ms"]
        for i in range(max(2, c - SLOTS + 2), c + 1):
            slot = RING + 8 * (i % SLOTS)
            digest, low, high = self.item(i)
            if digest is not None and read(observed, slot, 4) != digest:
                failures.append(f"item {i}: digest {read(observed, slot, 4):08x}, "
                                f"expected {digest:08x}")
                break
            least = (low - WINDOW_STATES) // 8
            most = -(-(high + WINDOW_STATES) // 8)
            measured = read(observed, slot + 4, 2)
            if not least <= measured <= most:
                span = f"{low}" if low == high else f"{low}..{high}"
                failures.append(f"item {i}: took {measured} phi/8 counts, expected "
                                f"{least}..{most} ({span} states)")
                break
        failures += self.extra(c, observed)
        # Observation falls after item c's TCNT sample and before item c+1's.
        elapsed = horizon * PHI // 1000
        _digest, _low, following = self.item(c + 1)
        earliest = 8 * total + self.setup_states - WINDOW_STATES
        latest = 8 * total + self.setup_states + following + WINDOW_STATES + 8
        if not earliest <= elapsed <= latest:
            failures.append(
                f"{c} items and {8 * total} Timer W states do not fit {horizon} ms "
                f"({elapsed} states): expected the observation between "
                f"{earliest} and {latest} states")
        return failures


HORIZONS = (1000, 2000, 4000, 8000, 16000, 32000, 64000, 128000, 256000, 512000, 1024000)
