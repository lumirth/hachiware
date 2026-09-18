"""ADC clock selection, external triggers and the battery sensing circuit."""

from diagnostic import Case
from .h8 import Program, handler


def cases():
    basis = {
        "kind": "software_reasoned",
        "source": "REJ09B0152-0300 Fig17.1/17.6; lumirth/pw BatterySample and BatteryCheckLow",
        "question": "Does P84 drive qualify battery sensing, with a supply-following AVCC and midpoint "
        "ADC quantization?",
        "limitation": "Assumes the configured effective sense drop. P84 must drive high to enable sensing.",
    }
    conditions = {"battery_sense_drop_mv": 600}
    for supply, code in [(3300, 838), (3000, 819), (2700, 796), (2400, 768)]:
        p = Program()
        p.byte(0xFFFA, 0x13)
        p.byte(0xFFBE, 7)
        p.code += bytes(20)
        for slot, (direction, latch, pull) in enumerate(
            [(16, 16, 0), (16, 0, 0), (0, 16, 16)]
        ):
            for a, v in [(0xFFEB, direction), (0xFFDB, latch), (0xF086, pull)]:
                p.byte(a, v)
            p.byte(0xFFBF, 0x80)
            p.code += bytes.fromhex("6a08ffbfe88046f8")
            p.code += bytes.fromhex("6b00ffbc6b80") + (0xF800 + 2 * slot).to_bytes(
                2, "big"
            )
        yield Case(
            f"adc-battery-supply-{supply}",
            p.finish(),
            {"ram": {"f800": f"{code << 6:04x}00000000"}},
            f"0,supply,{supply}\n",
            evidence=basis,
            conditions=conditions,
        )

    basis = {
        "kind": "documented",
        "source": "REJ09B0152-0300 §§17.3–17.4,17.7.3; Fig17.1 sample-and-hold circuit",
        "question": "Do all clock selectors complete, do PMRB/AMR/IEGR qualify physical triggers and "
        "vector38, and does an open mux retain its sampled charge?",
        "limitation": "Charge retention at an open mux follows the sample-and-hold circuit. Full-scale input requires AVCC at or below 3.3 V.",
    }
    p = Program()
    p.byte(0xFFFA, 0x13)
    p.code += bytes(20)
    for i, mode in enumerate([0x04, 0x14, 0x24, 0x34, 0x00]):
        p.byte(0xFFBE, mode)
        p.byte(0xFFBF, 0x80)
        p.code += bytes.fromhex("6a08ffbfe88046f8")
        p.code += bytes.fromhex("6b00ffbc6b80") + (0xF800 + 2 * i).to_bytes(2, "big")
    yield Case(
        "adc-clock-selections-and-open-mux",
        p.finish(),
        {"ram": {"f800": "ffc0" * 5}},
        "0,analog,pb0,3300\n",
        evidence=basis,
    )

    for rising in [False, True]:
        p = Program()
        for a, v in [
            (0xFFFA, 0x13),
            (0xFFCA, 8),
            (0xFFF2, 0x20 if rising else 0),
            (0xFFBE, 0x64),
            (0xFFF4, 0x40),
        ]:
            p.byte(a, v)
        p.code += bytes.fromhex("067f018040fc")
        image = handler(
            p.finish(), 38, "6b00ffbc6b80f8006a08fff76a88f802f8006a88fff740fe"
        )
        timeline = f"0,analog,pb0,3300\n0,digital,adtrg,{int(not rising)}\n100,digital,adtrg,{int(rising)}\n"
        yield Case(
            "adc-trigger-" + ("rising" if rising else "falling"),
            image,
            {"ram": {"f800": "ffc040"}, "interrupt_entries": 1},
            timeline,
            evidence=basis,
        )

    p = Program()
    p.byte(0xFFFA, 0x13)
    p.byte(0xFFBE, 0x64)  # TEST pin not selected as ADTRG.
    p.code += bytes(6000)
    p.code += bytes.fromhex("6a08ffbf6a88f8006b00ffbc6b80f802")
    yield Case(
        "adc-trigger-pin-gate",
        p.finish(),
        {"ram": {"f800": "3f", "f802": "0000"}},
        "0,digital,adtrg,1\n100,digital,adtrg,0\n",
        evidence=basis,
    )
