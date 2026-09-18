"""Oscillator selection and clock transitions through SLEEP."""

from diagnostic import Case
from .h8 import Program, handler


def cases():
    basis = {
        "kind": "documented",
        "source": "REJ09B0152-0300 §§4.1.1,4.3.4,5.5; Table10.3",
        "question": "Does SUBSTP stop the crystal, can ROSC/32 clock Timer W with that crystal stopped, "
        "and is OSCF read-only?",
    }
    p = Program()
    for a, v in [(0xFFFB, 0x44), (0xFFF5, 0x82), (0xF0F1, 0x40), (0xF0F0, 0x80)]:
        p.byte(a, v)
    p.code += bytes(1000)
    # Watch-selected TCNT cannot count while X1 is stopped. OSCF is status.
    p.code += bytes.fromhex("6b00f0f66b80f8006a08fff56a88f802")
    p.byte(0xFFF5, 0xA2)  # ROSC/32 works while SUBSTP stays set; OSCF stays zero.
    p.code += bytes.fromhex("6a08fff56a88f8036b00f0f647fa")
    p.byte(0xF804, 0xA5)
    yield Case(
        "oscillator-stopped-crystal-and-rosc-mux",
        p.finish(),
        {"ram": {"f800": "000080a0a5"}},
        None,
        evidence=basis,
    )

    basis = {
        "kind": "documented",
        "source": "REJ09B0152-0300 §§5.3.2,5.3.5",
        "question": "Does SLEEP enter each programmed clock mode and complete direct-transition exception "
        "handling?",
    }
    # Complete both clock transitions through SLEEP and the ordinary vector
    # 13 handler. Neither merely stopping instruction issue nor changing the
    # programmed SYSCR registers is enough to perform a direct transition.
    p = Program()
    p.code += bytes.fromhex("067f")
    p.byte(0xFFF0, 0xAF)
    p.byte(0xFFF1, 0xEB)
    p.code += bytes.fromhex("0180")
    p.byte(0xFFF0, 0xA7)
    p.byte(0xFFF1, 0xEB)
    p.code += bytes.fromhex("0180")
    p.byte(0xF781, 0xA5)
    image = handler(p.finish(), 13, "6a08f7800a086a88f7805670")
    yield Case(
        "direct-clock-transitions",
        image,
        {"ram": {"f780": "02a5"}, "interrupt_entries": 2},
        None,
        evidence=basis,
    )

    p = Program()  # reset CCR.I remains set
    p.byte(0xFFF0, 0xAF)
    p.byte(0xFFF1, 0xEB)
    p.code += bytes.fromhex("0180")
    p.byte(0xF781, 0xA5)
    image = handler(p.finish(), 13, "6a08f7800a086a88f7805670")
    yield Case(
        "direct-clock-masked",
        image,
        {"ram": {"f780": "0000"}, "interrupt_entries": 0},
        None,
        evidence=basis,
    )
