"""EEPROM page writes, command qualification and reset behavior."""

from diagnostic import Case
from .h8 import Program


EVIDENCE = {
    "kind": "documented",
    "source": "ST M95512 DS4192 Rev24 §§5.1,6.3.2,6.4,6.6",
    "question": "Do page wrapping, WEL, WRSR length, chip-select acceptance and reset preserve the "
    "EEPROM protocol?",
}


def cases():
    basis = EVIDENCE
    p = Program()
    for a, v in [
        (0xFFFB, 0x14),
        (0xF0E0, 0x8C),
        (0xF0E1, 0x40),
        (0xF0E2, 0x86),
        (0xF0E3, 0xC0),
        (0xFFE4, 7),
        (0xFFD4, 5),
        (0xF087, 8),
        (0xFFEC, 1),
        (0xFFDC, 1),
    ]:
        p.byte(a, v)
    p.byte(0xFFD4, 1)
    p.send(6)
    p.byte(0xFFD4, 5)
    p.byte(0xFFD4, 1)
    for value in [2, 0, 0x7E, 0xAA, 0xBB, 0xCC, 0xDD]:
        p.send(value)
    p.byte(0xFFD4, 5)
    yield Case(
        "serial-eeprom-page-wrap",
        p.finish(),
        {"eeprom": {"007e": "aabb", "0000": "ccdd"}, "nv_commits": 1},
        None,
        evidence=basis,
    )

    basis = EVIDENCE
    for name in [
        "eeprom-wel-during-write",
        "eeprom-overlong-status",
        "eeprom-power-before-cs",
        "eeprom-reset-during-write",
    ]:
        p = Program()
        for a, v in [
            (0xFFFB, 0x14),
            (0xF0E0, 0x8C),
            (0xF0E1, 0x40),
            (0xF0E2, 0x86),
            (0xF0E3, 0xC0),
            (0xFFE4, 7),
            (0xFFD4, 5),
            (0xF087, 8),
            (0xFFEC, 1),
            (0xFFDC, 1),
        ]:
            p.byte(a, v)
        if name == "eeprom-power-before-cs":
            # A committed control write shows that the program reached the
            # aborted one. Poll the status register until WIP clears.
            p.byte(0xFFD4, 1)
            p.send(6)
            p.byte(0xFFD4, 5)
            p.byte(0xFFD4, 1)
            for byte in (2, 0, 0x40, 0x5A):
                p.send(byte)
            p.byte(0xFFD4, 5)
            poll = len(p.code)
            p.byte(0xFFD4, 1)
            p.send(5)
            p.send(0)
            p.code += bytes.fromhex("0c89")  # MOV.B R0L,R1L keeps the status.
            p.byte(0xFFD4, 5)
            p.code += bytes.fromhex("7309")  # BTST #0,R1L: write in progress.
            p.code += bytes((0x46, (poll - len(p.code) - 2) & 255))
        p.byte(0xFFD4, 1)
        p.send(6)
        p.byte(0xFFD4, 5)
        p.byte(0xFFD4, 1)
        command = (
            [1, 0x8C, 0] if name == "eeprom-overlong-status" else [2, 0, 0x20, 0xA5]
        )
        for byte in command:
            p.send(byte)
        if name != "eeprom-power-before-cs":
            p.byte(0xFFD4, 5)
        timeline = None
        if name in ["eeprom-wel-during-write", "eeprom-overlong-status"]:
            p.byte(0xFFD4, 1)
            p.send(5)
            p.send(0)
            p.code += bytes.fromhex("6a88f800")
            p.byte(0xFFD4, 5)
            expected = {
                "ram": {"f800": "03" if name == "eeprom-wel-during-write" else "02"},
                "nv_commits": 1 if name == "eeprom-wel-during-write" else 0,
            }
        elif name == "eeprom-power-before-cs":
            timeline = "20000,power,0\n"
            expected = {"eeprom": {"0020": "ff", "0040": "5a"}, "nv_commits": 1}
        else:
            timeline = "1000,reset,0\n"
            expected = {"eeprom": {"0020": "a5"}, "nv_commits": 1}
        yield Case(name, p.finish(), expected, timeline, evidence=basis,
                   milliseconds=30 if name == "eeprom-power-before-cs" else 8)
