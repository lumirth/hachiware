"""RAM guests for the flash algorithms in Renesas section 6 and A414A/E."""

from __future__ import annotations
from diagnostic import Case


class Body:
    def __init__(self):
        self.code = bytearray()
        self.labels = {}
        self.jumps = []

    def emit(self, hex_bytes):
        self.code += bytes.fromhex(hex_bytes)

    def word(self, value):
        self.code += value.to_bytes(2, "big")

    def write(self, address, value):
        self.code += bytes((0xF8, value, 0x6A, 0x88, address >> 8, address & 255))

    def delay(self, count):
        self.emit("7902")
        self.word(count)
        self.emit("1b5246fc")

    def read(self, address, result):
        self.emit("6a08")
        self.word(address)
        self.emit("6a88")
        self.word(result)

    def mark(self, name):
        self.labels[name] = 0xF980 + len(self.code)

    def jump(self, name):
        self.emit("5a00")
        self.jumps.append((len(self.code), name))
        self.word(0)

    def copy(self, source, dest, length):
        self.emit("7905")
        self.word(source)
        self.emit("7906")
        self.word(dest)
        self.emit("7904")
        self.word(length)
        self.emit("7bd4598f")

    def setup(self):
        self.write(0xF02B, 0x80)
        self.write(0xF020, 0x40)
        self.delay(1)

    def finish(self, patches=()):
        self.emit("40fe")
        for at, name in self.jumps:
            self.code[at : at + 2] = self.labels[name].to_bytes(2, "big")
        if len(self.code) > 0x580:
            raise ValueError("flash diagnostic exceeds RAM body window")
        # All later instruction fetches, delay loops and result stores stay in RAM.
        loader = Body()
        loader.emit("7907ff70")
        loader.copy(0x400, 0xF980, len(self.code))
        loader.emit("5a00f980")
        image = bytearray(49152)
        image[:2] = bytes.fromhex("0100")
        image[0x100 : 0x100 + len(loader.code)] = loader.code
        image[0x400 : 0x400 + len(self.code)] = self.code
        for address, data in patches:
            image[address : address + len(data)] = data
        return bytes(image)


def cases():
    basis = {
        "kind": "documented",
        "source": "REJ09B0152-0300 §§6.2–6.7 and Table21.11; TN-H8*-A414A/E pp.3–4; H8/300H §2.8",
        "question": "Do RAM-executed control, pulse, verify, protection and target block operations "
        "preserve the flash contract?",
        "limitation": "Early reads retain the old verify latch; module standby initializes controller "
        "state and unavailable reads return FF in the selected circuit model. Programming "
        "assertions compare the cells after the guest verifies them.",
        "physical_device": "destructive flash modification; explicit sacrificial-device authorization "
        "required",
    }
    b = Body()
    result = 0xF900

    def read(a):
        nonlocal result
        b.read(a, result)
        result += 1

    read(0xF02B)
    b.write(0xF022, 255)
    b.write(0xF02B, 255)
    read(0xF02B)
    for a in range(0xF020, 0xF024):
        read(a)
    b.write(0xF020, 0xBF)
    read(0xF020)
    b.write(0xF021, 255)
    read(0xF021)
    b.write(0xF022, 255)
    read(0xF022)
    b.write(0xF020, 0xC0)
    read(0xF020)
    for value in [0x20, 0x40, 0x80, 0x21]:
        b.write(0xF023, value)
        read(0xF023)
    b.write(0xF023, 0x20)
    b.write(0xF02B, 0)
    for a in [0xF020, 0xF023, 0xF022]:
        b.write(a, 0)
    b.write(0xF02B, 0x80)
    for a in [0xF020, 0xF023, 0xF022]:
        read(a)
    b.write(0xF020, 0)
    read(0xF020)
    read(0xF023)
    yield Case(
        "flash-register-contract",
        b.finish(),
        {"ram": {"f900": "00800000000000008040204080004020800000"}},
        None,
        evidence=basis,
    )

    values = bytes.fromhex("123456789abcdef0")
    for early in [False, True]:
        b = Body()
        b.setup()
        b.write(0xF020, 0x44)
        b.delay(2)
        b.write(0x9000, 255)
        b.delay(1)
        b.emit("01006b00900001006b80f900")
        if early:
            b.emit("79019004f8ff6898691269136b82f9046b83f906")
            expected = "1234567812349abc"
        else:
            b.write(0x9004, 255)
            b.delay(1)
            b.emit("01006b00900401006b80f904")
            expected = "123456789abcdef0"
        b.write(0xF020, 0x40)
        b.delay(1)
        b.write(0xF020, 0)
        b.delay(61)
        b.copy(0x9000, 0xF910, 8)
        yield Case(
            "flash-verify-" + ("early-latch" if early else "settled"),
            b.finish([(0x9000, values)]),
            {"ram": {"f900": expected, "f910": values.hex()}},
            None,
            evidence={**basis, "kind": "software_reasoned"} if early else basis,
        )

    for address in [0x9000, 0x8000]:
        b = Body()
        b.setup()
        b.write(0xF023, 0x20)
        b.write(0xF020, 0x50)
        b.delay(31)
        b.write(0xF020, 0x51)
        b.emit("6a08")
        b.word(address)
        for i, a in enumerate([0xF021, 0xF020, 0xF023]):
            b.read(a, 0xF900 + i)
        b.write(0xF021, 0)
        b.write(0xF020, 0x50)
        b.delay(3)
        b.write(0xF020, 0x40)
        b.delay(3)
        b.read(0xF021, 0xF903)
        b.write(0xF020, 0x44)
        b.delay(2)
        b.write(0x9000, 255)
        b.delay(1)
        b.emit("01006b00900001006b80f904")
        b.write(0xF908, 0xA5)
        yield Case(
            "flash-protection-" + ("selected" if address == 0x9000 else "other-block"),
            b.finish([(0x9000, bytes([255]) * 128)]),
            {"ram": {"f900": "80512080ffffffffa5"}},
            None,
            evidence=basis,
        )

    b = Body()
    b.setup()
    b.write(0xF022, 0x80)
    b.write(0xF023, 0x20)
    b.emit("79019000")
    b.write(0xFFFA, 1)
    b.write(0xFFFA, 3)
    b.emit("681b")
    b.delay(12)
    b.emit("681c6a8bf9006a8cf901")
    for i, a in enumerate([0xF020, 0xF021, 0xF023, 0xF02B, 0xF022]):
        b.read(a, 0xF902 + i)
    yield Case(
        "flash-module-wake",
        b.finish([(0x9000, bytes([0xD3]))]),
        {"ram": {"f900": "ffd30000008080"}},
        None,
        evidence={**basis, "kind": "software_reasoned"},
    )

    # Table 6.4 defines the retry mask as wanted | ~verified. The guest retries
    # until verification succeeds, with a bound to report failed programming.
    wanted = bytes(i ^ 0xA5 for i in range(128))
    b = Body()
    b.copy(0xA00, 0xF780, 128)
    b.copy(0xA00, 0xF800, 128)
    b.setup()
    b.emit("790303e8")
    b.mark("retry")
    b.copy(0xF800, 0x9000, 128)
    b.write(0xF020, 0x50)
    b.delay(31)
    b.emit("792303e34504")
    b.jump("short-pulse")
    b.write(0xF020, 0x51)
    b.delay(121)
    b.write(0xF020, 0x50)
    b.jump("pulse-recovery")
    b.mark("short-pulse")
    b.write(0xF020, 0x51)
    b.delay(16)
    b.write(0xF020, 0x50)
    b.mark("pulse-recovery")
    b.delay(3)
    b.write(0xF020, 0x40)
    b.delay(3)
    b.write(0xF020, 0x44)
    b.delay(2)
    b.emit("790190007905f7807906f8007907f88079040020")
    b.mark("verify")
    b.emit("f8ff6898")
    b.delay(1)
    b.emit("01006910010069521fa047027073")  # Long sense, wanted, compare, mark failure.
    # Strengthening = previous retry | verified; R7 traverses RAM, with I=1
    # and NMI high throughout this call-free body.
    b.emit("0100696201f06402010069f20b9701006d52")
    # NOT.L ER0; OR.L ER2,ER0; MOV.L ER0,@ER6; ADDS #4,ER6.
    b.emit("173001f06420010069e00b96")
    b.emit("0b911b544704")
    b.jump("verify")  # ADD.L #4,ER1; DEC.W R4; loop.
    b.write(0xF020, 0x40)
    b.delay(1)
    b.emit("0d3079607fff792003e34404")
    b.jump("strengthened")
    b.copy(0xF880, 0x9000, 128)
    b.write(0xF020, 0x50)
    b.delay(31)
    b.write(0xF020, 0x51)
    b.delay(4)
    b.write(0xF020, 0x50)
    b.delay(3)
    b.write(0xF020, 0x40)
    b.delay(3)
    b.mark("strengthened")
    b.emit("73734604")
    b.jump("done")
    b.emit("72731b534704")
    b.jump("retry")
    b.write(0xF900, 0xEE)
    b.jump("halt")
    b.mark("done")
    b.write(0xF020, 0)
    b.delay(61)
    b.copy(0x9000, 0xF800, 128)
    b.write(0xF900, 0xA5)
    b.read(0xF021, 0xF901)
    b.read(0x8FFF, 0xF902)
    b.read(0x9080, 0xF903)
    b.mark("halt")
    yield Case(
        "flash-program-retry",
        b.finish([(0xA00, wanted), (0x8F80, bytes([255]) * 384)]),
        {"ram": {"f800": wanted.hex(), "f900": "a500ffff"}},
        None,
        evidence=basis,
        milliseconds=400,
    )

    for select, start, end, expected in [
        (0x10, 0x1000, 0x8000, "00ffffffff0000"),
        (0x20, 0x8000, 0xC000, "0000000000ffff"),
    ]:
        b = Body()
        b.setup()
        b.write(0xF023, select)
        b.emit("79030064")
        b.mark("retry")
        b.write(0xF020, 0x60)
        b.delay(61)
        b.write(0xF020, 0x62)
        b.delay(6142)
        b.write(0xF020, 0x60)
        b.delay(6)
        b.write(0xF020, 0x40)
        b.delay(6)
        b.write(0xF020, 0x48)
        b.delay(12)
        b.emit("7901")
        b.word(start)
        b.emit("7904")
        b.word((end - start) // 4)
        b.mark("verify")
        b.emit("f8ff6898")
        b.delay(1)
        b.emit("010069107a20ffffffff47067073")
        b.jump("verify-end")
        b.emit("0b911b544704")
        b.jump("verify")
        b.mark("verify-end")
        b.write(0xF020, 0x40)
        b.delay(2)
        b.emit("73734604")
        b.jump("done")
        b.emit("72731b534704")
        b.jump("retry")
        b.write(0xF900, 0xEE)
        b.jump("halt")
        b.mark("done")
        b.write(0xF020, 0)
        b.delay(61)
        b.write(0xF900, 0xA5)
        for i, a in enumerate([0xFFF, 0x1000, 0x3FFF, 0x4000, 0x7FFF, 0x8000, 0xBFFF]):
            b.read(a, 0xF901 + i)
        b.mark("halt")
        yield Case(
            f"flash-erase-eb{4 if select == 16 else 5}",
            b.finish(),
            {"ram": {"f900": "a5" + expected}},
            None,
            evidence=basis,
            milliseconds=1000,
        )
