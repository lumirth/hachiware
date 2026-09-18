"""Encode the H8 instructions and vectors used by diagnostic programs."""


class Program:
    def __init__(self) -> None:
        self.code = bytearray(bytes.fromhex("7907ff80"))

    def byte(self, address: int, value: int) -> None:
        self.code += bytes((0xF8, value, 0x6A, 0x88, address >> 8, address & 255))

    def word(self, address: int, value: int) -> None:
        self.code += bytes(
            (0x79, 0, value >> 8, value & 255, 0x6B, 0x80, address >> 8, address & 255)
        )

    def send(self, value: int) -> None:
        self.byte(0xF0EB, value)
        self.code += bytes.fromhex("6a08f0e4e80847f86a08f0e9")

    def lcd(self, data: bool, values: list[int]) -> None:
        for value in values:
            self.byte(0xFFD4, 6 if data else 4)
            self.send(value)
            self.byte(0xFFD4, 5)

    def finish(self) -> bytes:
        self.code += bytes.fromhex("40fe")
        image = bytearray(49152)
        image[:2] = bytes.fromhex("0100")
        if len(self.code) > 49152 - 0x100:
            raise ValueError("diagnostic code exceeds target flash")
        image[0x100 : 0x100 + len(self.code)] = self.code
        return bytes(image)


def handler(image: bytes, vector: int, code: str) -> bytes:
    image = bytearray(image)
    body = bytes.fromhex(code)
    if any(image[0x200 : 0x200 + len(body)]):
        raise ValueError("handler overlaps diagnostic program")
    image[vector * 2 : vector * 2 + 2] = bytes.fromhex("0200")
    image[0x200 : 0x200 + len(body)] = body
    return bytes(image)
