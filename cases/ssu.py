"""SSU shifting, holding registers and package pin selection."""

from diagnostic import Case
from .h8 import Program


def cases():
    basis = {
        "kind": "documented",
        "source": "REJ09B0152-0300 §§15.3–15.5; §8.4 and Appendix B.3 for the package mux",
        "question": "Do the serial pins, selection, shift/holding/receive registers, and qualified flags "
        "follow the SSU contract?",
    }
    for name, enable in [("ssu-receive-single", 0x60), ("ssu-receive-overrun", 0x40)]:
        p = Program()
        for a, v in [
            (0xFFFB, 0x14),
            (0xF087, 8),
            (0xF0E0, 0x8C),
            (0xF0E1, 0x40),
            (0xF0E2, 0xA6),
            (0xF0E3, enable),
        ]:
            p.byte(a, v)
        p.code += bytes.fromhex("6a08f0e9")  # dummy read starts receive-only clocks
        mask = 2 if enable == 0x60 else 0x40
        p.code += bytes.fromhex("6a08f0e4e8") + bytes([mask]) + bytes.fromhex("47f8")
        p.byte(0xF0E3, 0)  # RE clear retains unread data and ORER
        p.code += bytes.fromhex("6a08f0e46a88f8006a08f0e96a88f8016a08f0e46a88f802")
        yield Case(
            name,
            p.finish(),
            {"ram": {"f800": "06ff04" if enable == 0x60 else "46ff44"}},
            None,
            evidence=basis,
        )

    p = Program()
    for a, v in [
        (0xFFFB, 0x14),
        (0xF087, 8),
        (0xF0E0, 0x8C),
        (0xF0E1, 0x40),
        (0xF0E2, 0x80),
        (0xF0E3, 0xC0),
    ]:
        p.byte(a, v)
    p.send(0x35)  # complete first byte and consume SSRDR
    p.code += bytes.fromhex("6a08f0e4")
    p.byte(0xF0E4, 8)  # read-qualified TDRE clear repeats unchanged SSTDR
    p.code += bytes.fromhex("6a08f0e4e80247f8")
    p.byte(0xF0E3, 0)
    p.byte(0xF0E1, 0x60)  # SRES keeps status/data registers
    p.code += bytes.fromhex("6a08f0e46a88f8006a08f0e96a88f8016a08f0eb6a88f802")
    yield Case(
        "ssu-repeat-and-sequencer-reset",
        p.finish(),
        {"ram": {"f800": "0eff35"}},
        None,
        evidence=basis,
    )

    p = Program()
    for a, v in [
        (0xFFFB, 0x14),
        (0xF0E0, 0x8C),
        (0xF0E1, 0x40),
        (0xF0E2, 0x80),
        (0xF0E3, 0x80),
        (0xF0EB, 0x11),
        (0xF0EB, 0x22),
        (0xF0EB, 0x33),
    ]:
        p.byte(a, v)
    p.code += bytes.fromhex("6a08f0e4e80847f86a08f0e46a88f8006a08f0eb6a88f801")
    yield Case(
        "ssu-replace-queued-byte",
        p.finish(),
        {"ram": {"f800": "0c33"}},
        None,
        evidence=basis,
    )

    # External edges, not completed bytes, enter the package. Test all four
    # SPI phases, the alternate package mux, and clocked-sync LSB-first.
    for suffix, mode, mux, four_line in [
        ("mode-0", 0xE0, 0, True),
        ("mode-1", 0xC0, 0, True),
        ("mode-2", 0xA0, 0, True),
        ("mode-3", 0x80, 0, True),
        ("alternate-pins", 0xA0, 0x10, True),
        ("clocked-lsb", 0, 0, False),
    ]:
        p = Program()
        for a, v in [
            (0xFFFB, 0x14),
            (0xFFEC, 1),
            (0xFFDC, 1),
            (0xF085, mux),
            (0xF0E0, 0x0D),
            (0xF0E1, 0x40 if four_line else 0),
            (0xF0E2, mode),
            (0xF0E3, 0x40),
        ]:
            p.byte(a, v)
        p.code += bytes.fromhex("6a08f0e4e80247f86a08f0e96a88f800")
        p.code += bytes(256)  # allow the final half-clock and deselection
        p.code += bytes.fromhex("6a08f0e46a88f801")
        cs, clk, data = ("p93", "p92", "p91") if mux else ("p90", "p91", "p92")
        idle = 0 if mode & 0x40 else 1
        rows = [f"0,digital,{cs},1", f"0,digital,{clk},{idle}", f"500,digital,{cs},0"]
        for i in range(8):
            bit = (0x96 >> (7 - i if mode & 0x80 else i)) & 1
            rows += [
                f"{515 + 20 * i},digital,{data},{bit}",
                f"{520 + 20 * i},digital,{clk},{1 - idle}",
                f"{530 + 20 * i},digital,{clk},{idle}",
            ]
        rows += [f"680,digital,{cs},1"]
        # Clocked-sync inputs use SSI instead of the four-line slave's SSO.
        if not four_line:
            rows = [row.replace(",p92,", ",p93,") for row in rows]
        yield Case(
            "ssu-slave-" + suffix,
            p.finish(),
            {"ram": {"f800": "9604"}},
            "\n".join(rows) + "\n",
            evidence=basis,
        )

    p = Program()
    for a, v in [
        (0xFFFB, 0x14),
        (0xF0E0, 0x0D),
        (0xF0E1, 0x40),
        (0xF0E2, 0x80),
        (0xF0E3, 0xC0),
        (0xF0EB, 0x3C),
    ]:
        p.byte(a, v)
    p.code += bytes.fromhex("6a08f0e4e80147f86a08f0e46a88f8006a08f0e96a88f801")
    rows = ["0,digital,p90,1", "0,digital,p91,1", "500,digital,p90,0"]
    for i in range(3):
        rows += [f"{520 + 20 * i},digital,p91,0", f"{530 + 20 * i},digital,p91,1"]
    rows += ["580,digital,p90,1"]
    yield Case(
        "ssu-slave-deselect-in-frame",
        p.finish(),
        {"ram": {"f800": "0500"}},
        "\n".join(rows) + "\n",
        evidence=basis,
    )

    for suffix, high, mux, expected in [
        ("normal", 0x0D, 0, "0e961d0a"),
        ("alternate", 0x0D, 0x10, "0e961d05"),
        ("bidirectional", 0x4D, 0, "0c005d06"),
    ]:
        p = Program()
        for a, v in [
            (0xFFFB, 0x14),
            (0xF085, mux),
            (0xF0E0, high),
            (0xF0E1, 0x40),
            (0xF0E2, 0x80),
            (0xF0E3, 0x80 if high & 0x40 else 0xC0),
            (0xF0EB, 0x35),
        ]:
            p.byte(a, v)
        p.code += bytes.fromhex("6a08f0e4e80847f86a08f0e46a88f8006a08f0e96a88f801")
        p.code += bytes.fromhex("6a08f0e06a88f8026a08ffdc6a88f803")
        cs, clk, data = ("p93", "p92", "p91") if mux else ("p90", "p91", "p92")
        rows = [f"0,digital,{cs},1", f"0,digital,{clk},1", f"500,digital,{cs},0"]
        for i in range(8):
            rows += [
                f"{515 + 20 * i},digital,{data},{(0x96 >> (7 - i)) & 1}",
                f"{520 + 20 * i},digital,{clk},0",
                f"{530 + 20 * i},digital,{clk},1",
            ]
        rows += [f"800,digital,{cs},1"]
        yield Case(
            "ssu-slave-transmit-" + suffix,
            p.finish(),
            {"ram": {"f800": expected}},
            "\n".join(rows) + "\n",
            evidence=basis,
        )

    p = Program()
    for a, v in [
        (0xFFFB, 0x14),
        (0xF0E0, 0x8E),
        (0xF0E1, 0x40),
        (0xF0E2, 0x86),
        (0xF0E3, 0x80),
        (0xF0EB, 0x11),
    ]:
        p.byte(a, v)
    p.code += bytes.fromhex("6a08f0e4e80147f86a08f0e46a88f8006a08f0e06a88f801")
    yield Case(
        "ssu-master-selection-conflict",
        p.finish(),
        {"ram": {"f800": "010e"}},
        "0,digital,p90,0\n",
        evidence=basis,
    )

    p = Program()
    for a, v in [
        (0xFFFB, 0x14),
        (0xF087, 4),
        (0xF0E0, 0xCC),
        (0xF0E1, 0x40),
        (0xF0E2, 0xA6),
        (0xF0E3, 0x60),
    ]:
        p.byte(a, v)
    p.code += bytes.fromhex("6a08f0e96a08f0e4e80247f86a08f0e96a88f800")
    p.byte(0xF0E3, 0)
    yield Case(
        "ssu-bidirectional-receive",
        p.finish(),
        {"ram": {"f800": "ff"}},
        None,
        evidence=basis,
    )

    p = Program()
    for a, v in [(0xFFFB, 0x14), (0xF0E0, 0x8C), (0xF0E1, 0x40), (0xF0E3, 0x80)]:
        p.byte(a, v)
    # SOL reads the actual retained serial output, including the documented
    # SOLP 0->1 write-protection transition. Open-drain high releases the pin.
    for index, value in enumerate([0x94, 0x8C, 0x9C, 0xB4]):
        p.byte(0xF0E0, value)
        p.code += bytes.fromhex("6a08f0e06a88") + (0xF800 + 2 * index).to_bytes(
            2, "big"
        )
        p.code += bytes.fromhex("6a08ffdc6a88") + (0xF801 + 2 * index).to_bytes(
            2, "big"
        )
    p.byte(0xF087, 4)
    p.code += bytes.fromhex("6a08ffdc6a88f808")
    yield Case(
        "ssu-output-level-and-open-drain",
        p.finish(),
        {"ram": {"f800": "9c078c038c03bc0307"}},
        None,
        evidence=basis,
    )
