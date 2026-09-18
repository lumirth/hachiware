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
            timeline = "1000,power,0\n"
            expected = {"eeprom": {"0020": "ff"}, "nv_commits": 0}
        else:
            timeline = "1000,reset,0\n"
            expected = {"eeprom": {"0020": "a5"}, "nv_commits": 1}
        yield Case(name, p.finish(), expected, timeline, evidence=basis)
