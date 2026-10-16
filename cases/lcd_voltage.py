"""NT7508 power stages, regulated supplies and electrode amplitudes."""

from diagnostic import Case
from .h8 import Program

BASIS = {
    "kind": "documented",
    "source": "Novatek NT7508 V1.0 pp.10,25-28,42-44,48-50",
    "question": "Do power stages, boost, EV, resistor ratio, bias and temperature determine "
                "the LCD supplies and the COM/SEG electrode voltages?",
    "limitation": "Nominal steady-state equations; no capacitor transient or glass-response expectation. "
                  "F3 steps are interpreted as electronic-volume offsets in OTP test mode.",
}


def encode(values):
    return b"".join((0xffffffff if v is None else v).to_bytes(4, "little") for v in values).hex()


def guest(commands):
    p = Program()
    for a, v in [(0xFFFB, 0x14), (0xF0E0, 0x8C), (0xF0E1, 0x40),
                 (0xF0E2, 0x86), (0xF0E3, 0xC0), (0xFFE4, 7),
                 (0xFFD4, 5), (0xF087, 8), (0xFFEC, 1), (0xFFDC, 1)]:
        p.byte(a, v)
    p.lcd(False, [0x21, 0x81, 63, 0x50, 0x6d, 0x2f, *commands])
    return p


def cases():
    # EV=63, gain=4.5: V0=6.3 V; 1/5 bias gives 5.04/3.78/2.52/1.26 V.
    normal = [6_300_000, 5_040_000, 3_780_000, 2_520_000, 1_260_000]
    for name, commands, target, pump, levels in [
        ("all-stages", [], 6_300_000, 24_000_000, normal),
        ("converter-off", [0x2b], 6_300_000, None, [None]*5),
        ("regulator-off", [0x2d], 6_300_000, 24_000_000, [None]*5),
        ("follower-off", [0x2e], 6_300_000, 24_000_000, [6_300_000, None, None, None, None]),
        ("power-off", [0x28], 6_300_000, None, [None]*5),
        ("power-save", [0xa9], 6_300_000, None, [None]*5),
        ("power-save-release", [0xa9, 0xe1], 6_300_000, 24_000_000, normal),
        ("power-reenable", [0x28, 0x2f], 6_300_000, 24_000_000, normal),
        ("boost-3-headroom", [0x64], 6_300_000, 9_000_000, [None]*5),
        ("boost-4", [0x65], 6_300_000, 12_000_000, normal),
        ("boost-5", [0x66], 6_300_000, 15_000_000, normal),
        ("boost-6", [0x67], 6_300_000, 18_000_000, normal),
        ("boost-7", [0x6c], 6_300_000, 21_000_000, normal),
        ("ev-min", [0x81, 0], 4_410_000, 24_000_000,
         [4_410_000, 3_528_000, 2_646_000, 1_764_000, 882_000]),
        ("resistor-min", [0x20], 4_830_000, 24_000_000,
         [4_830_000, 3_864_000, 2_898_000, 1_932_000, 966_000]),
        ("resistor-max", [0x27, 0x81, 0], 10_584_000, 24_000_000,
         [10_584_000, 8_467_200, 6_350_400, 4_233_600, 2_116_800]),
        ("bias-12", [0x57], 6_300_000, 24_000_000,
         [6_300_000, 5_775_000, 5_250_000, 1_050_000, 525_000]),
        ("temperature-125", [], 6_142_500, 24_000_000,
         [6_142_500, 4_914_000, 3_685_500, 2_457_000, 1_228_500]),
        ("temperature-50", [0xf1, 1], 6_237_000, 24_000_000,
         [6_237_000, 4_989_600, 3_742_200, 2_494_800, 1_247_400]),
        ("trim-positive", [0x81, 62, 0xf4, 1, 0xf3, 1], 6_300_000, 24_000_000, normal),
        ("trim-negative", [0xf4, 1, 0xf3, 15], 6_270_000, 24_000_000,
         [6_270_000, 5_016_000, 3_762_000, 2_508_000, 1_254_000]),
        ("trim-normal-mode", [0xf3, 7], 6_300_000, 24_000_000, normal),
    ]:
        p = guest(commands)
        # A firmware marker also proves execution for unpowered-output cases.
        p.byte(0xf800, 0x5a)
        yield Case("lcd-voltage-" + name, p.finish(),
                   {"lcd_supply": {"0000": encode([target, pump, *levels])},
                    "ram": {"f800": "5a"}},
                   f"0,temperature,{45000 if name.startswith('temperature') else 25000}\n",
                   evidence=BASIS | ({"kind": "software_reasoned"} if name.startswith("trim") else {}))

    p = guest([])
    # Freeze the scan with external OSC selected and no clock connected. Row 0
    # selects COM32. SEG0 has black data, SEG1 white, at the first PWM quantum.
    p.lcd(False, [0x44, 32, 0x48, 64, 0xf7, 1, 0x8e, 0x99, 0x8f, 0x99])
    p.lcd(True, [1, 1, 0, 0])
    p.lcd(False, [0xab, 0xaf])
    yield Case("lcd-voltage-electrodes", p.finish(), {
        "lcd_supply": {"0000": encode([6_300_000, 24_000_000, *normal])},
        "lcd_drive": {"0000": encode([1_260_000]), "0080": encode([6_300_000]),
                      "0204": encode([0, 2_520_000])},
    }, "0,temperature,25000\n", evidence=BASIS)

    p = guest([0xab, 0xaf, 0xa9])
    yield Case("lcd-voltage-power-save-electrodes", p.finish(), {
        "lcd_supply": {"0000": encode([6_300_000, *([None]*6)])},
        "lcd_drive": {"0000": encode([0]*257)},
    }, "0,temperature,25000\n", evidence=BASIS)
