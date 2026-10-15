"""Assemble a diagnostic program from H8/300H assembly text."""

from .asm import assemble


def image(body: str, vectors: dict[int, str] | None = None) -> bytes:
    """Reset to ``start`` at 0x100 with the stack at 0xFF80, then ``body``.

    The program ends in a branch to itself. ``vectors`` maps vector numbers
    to labels defined in ``body``.
    """
    lines = [".vector 0, start"]
    lines += [f".vector {n}, {label}" for n, label in (vectors or {}).items()]
    lines += [".org 0x100", "start:", "    mov.l #0xff80, er7", body, "done:", "    bra done"]
    return assemble("\n".join(lines))[0]


def record(address: int) -> str:
    """Store ER0 and two copies of CCR (captured first) at ``address``."""
    return (f"    stc ccr, r2l\n    mov.l er0, @{address:#x}\n"
            f"    mov.b r2l, @{address + 4:#x}\n    mov.b r2l, @{address + 5:#x}\n")


_serial = [0]


def record_flags(address: int, memory: str | None = None) -> str:
    """Store ER0 and two copies of N, Z, V and C read with conditional branches.

    Branches leave CCR unchanged, so the flags are decoded before anything
    alters them; V is N xor LT. This avoids STC, so a case does not depend on
    an instruction other than the one it tests. ``memory`` loads R0L from
    that byte after the flags are taken.
    """
    _serial[0] += 1
    tag = f"rf{_serial[0]}"
    lines = []

    def test(prefix):
        depth = len(prefix)
        if depth == 0:
            return "bmi"
        if depth == 1:
            return "beq"
        if depth == 2:  # V = 1 when LT differs from N
            return "bge" if prefix[0] == "1" else "blt"
        return "bcs"

    def emit(prefix):
        if len(prefix) == 4:
            n, z, v, c = (int(b) for b in prefix)
            lines.append(f"{tag}_{prefix}:\n    mov.b #{n << 3 | z << 2 | v << 1 | c}, r2l\n"
                         f"    bra {tag}_done")
            return
        lines.append(f"{tag}_{prefix}n:\n    {test(prefix)} {tag}_{prefix}1n"
                     if len(prefix) < 3 else
                     f"{tag}_{prefix}n:\n    {test(prefix)} {tag}_{prefix}1")
        target = f"{tag}_{prefix}0n" if len(prefix) < 3 else f"{tag}_{prefix}0"
        lines.append(f"    bra {target}")
        emit(prefix + "0")
        emit(prefix + "1")

    emit("")
    lines.append(f"{tag}_done:")
    if memory:
        lines.append(f"    mov.b {memory}, r0l")
    lines.append(f"    mov.l er0, @{address:#x}\n    mov.b r2l, @{address + 4:#x}\n"
                 f"    mov.b r2l, @{address + 5:#x}")
    return "\n".join(lines) + "\n"
