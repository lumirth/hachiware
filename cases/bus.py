"""Register widths, byte lanes and digital access to analog pins."""

from diagnostic import Case
from .h8 import Program


def cases():
    basis = {
        "kind": "software_reasoned",
        "source": "REJ09B0152-0300 §§2.3.2,2.5–2.6,8.5.1,8.5.3; TN-H8*-A414A/E memory map",
        "question": "Do ordinary lane/alignment/wrap accesses complete without invented faults, and do "
        "comparator-enabled PB pins retain digital read access?",
        "limitation": "Byte reads select a word register lane; only word writes qualify its latch. The selected decoder returns zero for unassigned reads. Comparator and ADC pin mux behavior follows the manual.",
    }
    p = Program()
    p.word(0xF0F8, 0x1234)
    p.code += bytes.fromhex("6a08f0f86a88f8006a08f0f96a88f801")
    p.byte(0xF0F8, 0xAB)
    p.byte(0xF0F9, 0xCD)
    p.code += bytes.fromhex("6b00f0f86b80f802")
    yield Case(
        "register-native-word-byte-lanes",
        p.finish(),
        {"ram": {"f800": "12341234"}},
        None,
        evidence=basis,
    )

    p = Program()
    for i, v in enumerate([3, 0xFC]):
        p.byte(0xF088, v)
        p.code += bytes((0x6A, 8, 0xF0, 0x88, 0x6A, 0x88, 0xF8, i))
    p.word(0xF084, 0xAB12)
    p.word(0xC000, 0xCD34)
    p.code += bytes.fromhex("6b00f0846b80f8026b00c0006b80f80401006b00fffe01006b80f806")
    yield Case(
        "register-holes-and-mixed-word",
        p.finish(),
        {"ram": {"f800": "00000012000000000100"}},
        None,
        evidence=basis,
    )

    p = Program()
    p.byte(0xFFFB, 6)
    p.byte(0xF0DC, 0x80)
    p.code += bytes.fromhex("6a08ffde6a88f800")
    p.byte(0xFFBE, 8)
    p.code += bytes.fromhex("6a08ffde6a88f801")
    yield Case(
        "register-comparator-digital-read",
        p.finish(),
        {"ram": {"f800": "1000"}},
        "0,analog,pb4,3000\n",
        evidence=basis,
    )
