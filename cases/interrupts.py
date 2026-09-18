"""Interrupt admission, exception stack contents and NMI wake."""

from diagnostic import Case
from .h8 import Program, handler


def cases():
    basis = {
        "kind": "documented",
        "source": "REJ09B0152-0300 §§3.7–3.8.4,10.4; H8/300H software manual §1.1; H8/3318 §2.3.2",
        "question": "Do exception stack contents, enable-clear admission, source-clear cancellation and "
        "pin-selection flag settling follow the target contract?",
        "limitation": "Timer match is seven phi states after start, strictly between BCLR operand read "
        "and write; CCR duplication follows the explicitly inherited H8/300 stack format.",
    }
    for nop, high in [(False, False), (True, False), (False, True)]:
        p = Program()
        p.code += bytes.fromhex("f901f8fe6a89ffca")
        if nop:
            p.code += bytes.fromhex("0000")
        p.code += bytes.fromhex("38f66a08fff66a88f800")
        name = "irq-mux-" + (
            "high" if high else "settled" if nop else "immediate-clear"
        )
        yield Case(
            name,
            p.finish(),
            {"ram": {"f800": "00" if nop or high else "01"}},
            f"0,analog,pb0,{3000 if high else 0}\n",
            evidence=basis,
        )

    for clear_source in [False, True]:
        p = Program()
        p.code = bytearray(bytes.fromhex("7907ff70"))
        for a, v in [(0xFFFB, 0x44), (0xF0F1, 0), (0xF0F2, 1)]:
            p.byte(a, v)
        p.word(0xF0F8, 0 if clear_source else 6)
        p.code += bytes.fromhex("7900") + (0xF0F3 if clear_source else 0xF0F2).to_bytes(
            2, "big"
        )
        # phi clock; leaving GRA=6 occurs seven states after starting, between
        # BCLR's operand read/NEXT and write. GRA=0 sets before its operand read.
        p.code += bytes.fromhex("f980067f00006a89f0f0")
        return_pc = 0x100 + len(p.code) + 4
        p.code += bytes.fromhex("7d007200")
        p.byte(0xF802, 0xA5)
        p.code += bytes.fromhex("6a08f0f26a88f803")
        image = handler(
            p.finish(), 35, "6a08f0f36a88f8006a08f0f26a88f801f8006a88f0f35670"
        )
        expected = {
            "ram": {"f800": "0000a571" if clear_source else "7170a570"},
            "interrupt_entries": 0 if clear_source else 1,
        }
        if not clear_source:
            expected["ram"]["ff6e"] = f"{return_pc:04x}"
        yield Case(
            "irq-"
            + ("source-clear-cancels" if clear_source else "enable-clear-admission"),
            image,
            expected,
            None,
            evidence=basis,
        )

    p = Program()
    p.code = bytearray(bytes.fromhex("7907ff700735570040fe"))
    image = handler(p.finish(), 8, "40fe")
    yield Case(
        "exception-ccr-stack-word",
        image,
        {"ram": {"ff6c": "35350108"}},
        None,
        evidence=basis,
    )

    basis = {
        "kind": "documented",
        "source": "REJ09B0152-0300 §§3.4.1,3.5.1,5.2",
        "question": "Does each selected NMI edge wake despite I=1, without retriggering a held level?",
    }
    p = Program()
    p.code += bytes.fromhex("0780018040fc")
    image = handler(p.finish(), 7, "6a08f7800a086a88f7805670")
    yield Case(
        "nmi-masked-sleep",
        image,
        {"ram": {"f780": "02"}, "interrupt_entries": 2},
        "100,nmi,0\n300,nmi,1\n500,nmi,0\n",
        evidence=basis,
    )
