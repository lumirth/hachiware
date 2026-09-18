"""Original GPIO I2C guests, Bosch BMA150 rev1.6 section 4.2.

Literal read/ACK expectations come from the protocol and register map. P90 is
CSB, P91 SCL, P92 SDA; the MCU's hardware IIC is a different pair of pins.
"""

from diagnostic import Case
from .h8 import Program

BASIS = {
    "kind": "documented",
    "source": "Bosch BMA150 Rev1.6 §§3.3.3,3.3.6–7,4.1.1,4.2–4.2.1; H8/38602R §8.4",
    "question": "Do GPIO SDA/clock edges implement the fixed address, paired writes, incrementing "
    "reads, ACK protection, aborts and live CSB selection?",
    "limitation": "Sleep/wake bus ACK and retaining the final reset ACK are circuit inferences; no "
    "pad slew or exact sub-edge propagation is asserted.",
}


class Bus:
    def __init__(self, Program):
        self.p = Program()
        self.expected = []
        self.selected = False
        self.sdo = None
        for address, value in [
            (0xFFFB, 0x34),
            (0xFFD4, 5),
            (0xFFE4, 7),
            (0xFFDC, 3),
            (0xFFEC, 3),
            (0xF087, 12),
        ]:
            self.p.byte(address, value)
        self.p.code += bytes(12000)  # Allow cold acquisition before bus traffic.

    def clock(self, high):
        self.p.byte(
            0xFFDC, int(not self.selected) | (2 if high else 0) | (8 if self.sdo else 0)
        )

    def data(self, high):
        # PDR92 stays zero. Input releases SDA and enables PUCR92; output is low.
        self.p.byte(0xFFEC, (3 if high else 7) | (8 if self.sdo is not None else 0))

    def start(self):
        self.clock(False)
        self.data(True)
        self.clock(True)
        self.data(False)
        self.clock(False)

    def stop(self):
        self.data(False)
        self.clock(True)
        self.data(True)

    def bits(self, value, count=8):
        for bit in range(count):
            self.data(bool(value & (0x80 >> bit)))
            self.clock(True)
            self.clock(False)

    def store(self, register, expected):
        slot = len(self.expected)
        assert slot < 256
        self.p.code += bytes((0x6A, 0x80 | register, 0xF8, slot))
        self.expected.append(expected)

    def send(self, value, ack=0):
        self.bits(value)
        self.data(True)
        self.clock(True)
        self.p.code += bytes.fromhex("6a08ffdce804")  # PDR92, input pad.
        self.store(8, ack)
        self.clock(False)

    def read(self, expected, ack=False):
        self.data(True)
        self.p.code += bytes.fromhex("f900")  # R1L accumulates the incoming byte.
        for _ in range(8):
            self.clock(True)
            self.p.code += bytes.fromhex("10096a08ffdce8044702c901")
            self.clock(False)
        self.store(9, expected)
        self.data(not ack)
        self.clock(True)
        self.clock(False)
        self.data(True)

    def pointer(self, address, repeated=True):
        self.start()
        self.send(0x70)
        self.send(address)
        if not repeated:
            self.stop()
        self.start()
        self.send(0x71)

    def write(self, *pairs):
        self.start()
        self.send(0x70)
        for address, value in pairs:
            self.send(address)
            self.send(value)
        self.stop()

    def case(self, name, *, evidence=BASIS):
        return Case(
            "sensor-i2c-" + name,
            self.p.finish(),
            {"ram": {"f800": bytes(self.expected).hex()}},
            evidence=evidence,
        )


def cases():
    b = Bus(Program)
    # SDO is not an address strap. Both levels leave address 38 unchanged.
    for sdo in (False, True):
        b.sdo = sdo
        b.start()
        b.send(0x72, ack=4)
        b.stop()
        b.pointer(0 if not sdo else 0x80, repeated=sdo)
        b.read(2, ack=True)
        b.read(0x10)
        b.stop()
    yield b.case("identity-and-address")

    b = Bus(Program)
    # Writes contain alternating address/data pairs; reads increment instead.
    b.write((0x0C, 0x20), (0x0D, 2))
    b.pointer(0x0C)
    b.read(0x20, ack=True)
    b.read(2)
    b.read(0xFF)  # A NACK terminates output without requiring STOP.
    b.stop()
    b.write((0x16, 0xA5))  # Blocked access still ACKs its address and data.
    b.pointer(0x16)
    b.read(0xFF)
    b.stop()
    b.write((0x0A, 0x10), (0x16, 0xA5))
    b.pointer(0x16)
    b.read(0xA5)
    b.stop()
    yield b.case("pairs-and-protection")

    b = Bus(Program)
    b.write((0x0C, 0x55))
    b.start()
    b.send(0x70)
    b.send(0x0C)
    b.bits(0xA5, 4)
    b.stop()
    b.pointer(0x0C)
    b.read(0x55)
    b.stop()
    b.start()
    b.send(0x70)
    b.send(0x0C)
    b.bits(0, 3)
    b.start()
    b.send(0x71)
    b.read(0x55)
    b.stop()
    b.selected = True
    b.start()
    b.send(0x70, ack=4)
    b.stop()
    b.selected = False
    b.pointer(0)
    b.read(2)
    b.stop()
    yield b.case("partial-byte-and-selection")

    b = Bus(Program)
    b.write((0x0A, 1))  # Sleeping decoder must still accept wake/reset commands.
    b.pointer(0)
    b.read(0xFF)
    b.stop()
    b.write((0x0A, 0))
    b.p.code += bytes(4000)
    b.pointer(0)
    b.read(2)
    b.stop()
    b.write((0x0A, 2))  # Reset does not retract the completed data byte's ACK.
    b.p.code += bytes(4000)
    b.pointer(0)
    b.read(2)
    b.stop()
    yield b.case(
        "sleep-wake-and-reset", evidence={**BASIS, "kind": "software_reasoned"}
    )
