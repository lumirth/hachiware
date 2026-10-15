"""Encode the H8 instructions and vectors used by diagnostic programs."""

FLAGS = 0xBF00
"""Address of the shared NZVC decoder that ``record_er0_flags`` calls."""


def _flag_decoder() -> bytes:
    """A subroutine that leaves N<<3 | Z<<2 | V<<1 | C in R2L.

    It reads the flags only with conditional branches, which leave CCR
    unchanged, so a case observes the instruction under test without also
    depending on STC. V is N xor LT. JSR and RTS do not change CCR.
    """
    from .asm import assemble

    lines = [f".org {FLAGS:#x}", "flags:"]

    def test(prefix):
        return ("bmi", "beq", "bge" if prefix[:1] == "1" else "blt", "bcs")[len(prefix)]

    def emit(prefix):
        if len(prefix) == 4:
            n, z, v, c = (int(b) for b in prefix)
            lines.append(f"f{prefix}:\n    mov.b #{n << 3 | z << 2 | v << 1 | c}, r2l\n    rts")
            return
        lines.append(f"f{prefix}n:\n    {test(prefix)} "
                     + (f"f{prefix}1n" if len(prefix) < 3 else f"f{prefix}1"))
        lines.append("    bra " + (f"f{prefix}0n" if len(prefix) < 3 else f"f{prefix}0"))
        emit(prefix + "0")
        emit(prefix + "1")

    emit("")
    image = assemble("\n".join(lines))[0]
    return image[FLAGS:FLAGS + 0x100]


class Program:
    def __init__(self) -> None:
        self.code = bytearray(bytes.fromhex("7907ff80"))
        self.uses_flags = False

    def byte(self, address: int, value: int) -> None:
        self.code += bytes((0xF8, value, 0x6A, 0x88, address >> 8, address & 255))

    def word(self, address: int, value: int) -> None:
        self.code += bytes(
            (0x79, 0, value >> 8, value & 255, 0x6B, 0x80, address >> 8, address & 255)
        )

    def send(self, value: int) -> None:
        self.byte(0xF0EB, value)
        self.code += bytes.fromhex("6a08f0e4e80847f86a08f0e9")

    def record_er0_ccr(self, address: int) -> None:
        """Store ER0 then two copies of its CCR, using R2L as scratch.

        STC captures CCR before MOV changes it. Six-byte records keep subsequent
        MOV.L destinations even, as the H8 requires.
        """
        self.code += bytes.fromhex("020a01006b80") + address.to_bytes(2, "big")
        for offset in (4, 5):
            self.code += bytes.fromhex("6a8a") + (address + offset).to_bytes(2, "big")

    def record_er0_flags(self, address: int) -> None:
        """Store ER0 then two copies of its N, Z, V and C flags as one nibble.

        The flags are read by the shared branch decoder, so this does not
        depend on STC. Six-byte records keep MOV.L destinations even.
        """
        self.uses_flags = True
        self.code += bytes.fromhex("5e00") + FLAGS.to_bytes(2, "big")
        self.code += bytes.fromhex("01006b80") + address.to_bytes(2, "big")
        for offset in (4, 5):
            self.code += bytes.fromhex("6a8a") + (address + offset).to_bytes(2, "big")

    def flags_r2l(self) -> None:
        """Leave the current N, Z, V and C in R2L using the branch decoder."""
        self.uses_flags = True
        self.code += bytes.fromhex("5e00") + FLAGS.to_bytes(2, "big")

    def lcd(self, data: bool, values: list[int]) -> None:
        for value in values:
            self.byte(0xFFD4, 6 if data else 4)
            self.send(value)
            self.byte(0xFFD4, 5)

    def finish(self) -> bytes:
        self.code += bytes.fromhex("40fe")
        image = bytearray(49152)
        image[:2] = bytes.fromhex("0100")
        limit = (FLAGS if self.uses_flags else 49152) - 0x100
        if len(self.code) > limit:
            raise ValueError("diagnostic code exceeds target flash")
        image[0x100 : 0x100 + len(self.code)] = self.code
        if self.uses_flags:
            image[FLAGS : FLAGS + 0x100] = _flag_decoder()
        return bytes(image)


def handler(image: bytes, vector: int, code: str) -> bytes:
    image = bytearray(image)
    body = bytes.fromhex(code)
    if any(image[0x200 : 0x200 + len(body)]):
        raise ValueError("handler overlaps diagnostic program")
    image[vector * 2 : vector * 2 + 2] = bytes.fromhex("0200")
    image[0x200 : 0x200 + len(body)] = body
    return bytes(image)
