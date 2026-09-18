"""LCD plane layout, addressing and display command priority."""

from diagnostic import Case
from .h8 import Program


def cases():
    basis = {
        "kind": "documented",
        "source": "Novatek NT7508 V1.0 pp.15–17,29,34–41,44–46; lumirth/pw DisplayFill for plane order",
        "question": "Do serial LCD commands preserve physical RAM, map both planes before viewport "
        "cropping, and obey display/duty/reset priority?",
    }
    for name in [
        "lcd-bitplanes",
        "lcd-segment-reversal",
        "lcd-duty-override",
        "lcd-icon-reset",
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
        p.lcd(False, [0x44, 32, 0x48, 64, 0xAB, 0x2F, 0xE8, 0xAF])
        if name == "lcd-bitplanes":
            p.lcd(True, [1, 0, 0, 1, 1, 1])
            expected = {"pixels": {"0000": "02010300"}, "display_on": True}
        elif name == "lcd-segment-reversal":
            p.lcd(False, [0x17, 0x0D, 0xA1])
            p.lcd(True, [1, 1, 0, 1, 1, 0])
            expected = {"pixels": {"0000": "02010300"}, "lcd": {"00fa": "010100010100"}}
        elif name == "lcd-duty-override":
            p.lcd(False, [0x48, 16, 0xA7, 0xA5, 0x48, 0xFF])
            expected = {"pixels": {"0000": "03030303", "05ff": "03000000"}}
        else:
            p.lcd(False, [0xA3])
            p.lcd(True, [0xFE, 0xFF])
            p.lcd(False, [0xA2])
            p.lcd(True, [0xFF])
            p.lcd(False, [0xB0])
            p.lcd(True, [0x55])
            p.lcd(False, [0x40, 64, 0xE2])
            p.lcd(True, [0xAA])
            expected = {
                "icons": {"0000": "00010100"},
                "lcd": {"0000": "aa000055"},
                "display_on": True,
                "display_start": 0,
            }
        yield Case(name, p.finish(), expected, None, evidence=basis)
