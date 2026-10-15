"""Instruction execution states for assembled guest code.

REJ09B0152-0300 Appendix A.3 gives states = 2I + 2J + 2K + L*SL + M*SM + N for
code, vectors and stack in on-chip memory. Table A.4 supplies I..N per
instruction form. SL and SM depend on the accessed location: on-chip memory takes
two states per access; peripheral registers take the states transcribed in
``spec/register_access.tsv`` (section 20.1), and a word access to an 8-bit
register is two byte accesses.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _registers() -> dict[int, tuple[int, int]]:
    table = {}
    for line in (ROOT / "spec" / "register_access.tsv").read_text().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        address, _name, bits, states, _page = line.split()
        table[int(address, 16)] = (int(bits), int(states))
    return table


REGISTERS = _registers()


def access_states(address: int | None, width: int) -> int:
    """States for one byte (width 1) or word (width 2) data access."""
    if address is None:
        return 2
    address &= 0xFFFF
    if address in REGISTERS or (address & ~1) in REGISTERS:
        bits, states = REGISTERS.get(address, REGISTERS.get(address & ~1))
        if width == 2 and bits == 8:
            return 2 * states
        return states
    return 2


def cycles(entry, data_address: int | None = None, eepmov_count: int = 0):
    """Return (I, J, K, L, M, N, address) for one listing entry."""
    _pc, mnemonic, ops, length = entry
    base, _, suffix = mnemonic.partition(".")
    kinds = [o[0] for o in ops]
    memory = [o for o in ops if o[0] in ("ind", "disp", "postinc", "predec", "abs")]
    address = data_address
    if memory and memory[0][0] == "abs":
        address = memory[0][2]
        if memory[0][3] == 8 and address is not None:
            address |= 0xFF00
    auto = 2 if any(k in ("postinc", "predec") for k in kinds) else 0
    words = length // 2
    if base == "mov" and memory:
        if suffix == "b":
            return (words, 0, 0, 1, 0, auto, address)
        return (words, 0, 0, 0, 2 if suffix == "l" else 1, auto, address)
    if base in ("push", "pop"):
        return (words, 0, 0, 0, 2 if words == 2 else 1, 2, None)
    if base in ("mulxu", "mulxs", "divxu", "divxs"):
        return (words, 0, 0, 0, 0, 12 if suffix == "b" else 20, None)
    if base in ("bset", "bclr", "bnot", "bst", "bist") and memory:
        return (2, 0, 0, 2, 0, 0, address)
    if base in ("btst", "bld", "bild", "band", "biand", "bor", "bior", "bxor", "bixor") and memory:
        return (2, 0, 0, 1, 0, 0, address)
    if base.startswith("b") and base not in (
        "band", "biand", "bor", "bior", "bxor", "bixor", "bld", "bild", "bst", "bist",
        "bset", "bclr", "bnot", "btst",
    ):
        stack = 1 if base == "bsr" else 0
        return (2, 0, stack, 0, 0, 2 if length == 4 else 0, None)
    if base in ("jmp", "jsr"):
        stack = 1 if base == "jsr" else 0
        kind = kinds[0]
        if kind == "ind":
            return (2, 0, stack, 0, 0, 0, None)
        if kind == "mem":
            return (2, 1, stack, 0, 0, 0 if base == "jsr" else 2, None)
        return (2, 0, stack, 0, 0, 2, None)
    if base == "rts":
        return (2, 0, 1, 0, 0, 2, None)
    if base == "rte":
        return (2, 0, 2, 0, 0, 2, None)
    if base == "trapa":
        return (2, 1, 2, 0, 0, 4, None)
    if base in ("ldc", "stc") and memory:
        return (words, 0, 0, 0, 1, auto, address)
    if base == "eepmov":
        return (2, 0, 0, 2 * eepmov_count + 2, 0, 0, None)
    return (words, 0, 0, 0, 0, 0, None)


def states(entry, data_address: int | None = None, eepmov_count: int = 0) -> int:
    i, j, k, l, m, n, address = cycles(entry, data_address, eepmov_count)
    return 2 * (i + j + k) + l * access_states(address, 1) + m * access_states(address, 2) + n


def span(listing, start: int, end: int, overrides: dict | None = None) -> int:
    """Sum states of instructions with start <= address < end, executed once each.

    ``overrides`` maps an instruction address to the data address it accesses
    when the operand is register indirect.
    """
    overrides = overrides or {}
    return sum(
        states(entry, overrides.get(entry[0]))
        for entry in listing
        if start <= entry[0] < end
    )


INTERRUPT_ENTRY = 14
"""States from acceptance to the first handler fetch (Table 3.4, excluding the wait)."""
