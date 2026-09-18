"""AEC, RTC and timer counting, capture and interrupt behavior."""

from diagnostic import Case
from .h8 import Program, handler


RTC_EVIDENCE = {
    "kind": "documented",
    "source": "REJ09B0152-0300 §§8.1.4,11.3–11.5; REJ06B0514 RCS=1xxx table",
    "question": "Do calendar updates preserve raw digit fields and a pending busy update, and does "
    "TMOW drive P10 independently of RUN?",
    "limitation": "Busy-write precedence and malformed digit carry are local counter/latch "
    "inferences; no exact initial busy phase is asserted.",
}


def cases():
    basis = {
        "kind": "software_reasoned",
        "source": "REJ09B0152-0300 §§13.3–13.6",
        "question": "Do documented writable reserved fields read back, and do live PWM changes resume "
        "physical output after a disconnected source?",
        "limitation": "PWCK111 disconnects the clock and ECPWDR reads zero in the selected local model; "
        "these values are not guaranteed by the manual.",
    }
    p = Program()
    for a, v in [
        (0xFFFB, 0x0C),
        (0xFFC0, 0x20),
        (0xFF92, 0xFD),
        (0xFF94, 0x0F),
        (0xFF95, 0x3F),
    ]:
        p.byte(a, v)
    for i, a in enumerate([0xFF92, 0xFF94, 0xFF95]):
        p.code += bytes((0x6A, 8, a >> 8, a & 255, 0x6A, 0x88, 0xF8, i))
    p.word(0xFF8C, 3)
    p.word(0xFF8E, 1)
    p.byte(0xFF92, 0xFF)
    p.code += bytes.fromhex("6b00ff8e6b80f804")
    # PWCK=111 parks the counter; live latches and a valid source resume it.
    p.word(0xFF8C, 7)
    p.word(0xFF8E, 2)
    p.byte(0xFF94, 2)
    p.code += bytes.fromhex("6a08ffd4e80447f86a88f806")
    yield Case(
        "aec-live-pwm-and-reserved-fields",
        p.finish(),
        {"ram": {"f800": "fd0f3f", "f804": "000004"}},
        None,
        evidence=basis,
    )

    basis = {
        "kind": "software_reasoned",
        "source": "REJ09B0152-0300 §§9.2–9.4 TLB/TCB path and shared clock selection",
        "question": "Do live TLB/mode writes continue counting and preserve the reload/overflow "
        "relationship?",
        "limitation": "Writing TLB while counting is outside recommended programming; both connected "
        "latches accept the write in this selected circuit model.",
    }
    p = Program()
    p.byte(0xFFFA, 7)
    p.byte(0xF0D0, 0x78)
    p.byte(0xF0D1, 0x42)
    p.code += bytes.fromhex("6a08f0d16a88f800")
    p.byte(0xF0D0, 0xF8)
    p.byte(0xF0D0, 0xFE)
    p.code += bytes.fromhex("6a08f0d16a88f801")
    p.byte(0xF0D1, 0xFF)
    p.byte(0xF0D0, 0xF8)
    p.code += bytes.fromhex("6a08fff7e80447f86a88f8026a08f0d16a88f803")
    yield Case(
        "timer-b1-live-load-and-mode",
        p.finish(),
        {"ram": {"f800": "424204ff"}},
        None,
        evidence=basis,
    )

    basis = RTC_EVIDENCE
    for busy_write in [False, True]:
        p = Program()
        p.byte(0xFFB1, 0x12)
        p.byte(0xFFB1, 0xA2)
        for a, v in [(0xF06C, 0x10), (0xF06C, 0), (0xF06F, 0x0F), (0xF06D, 0x7F)]:
            p.byte(a, v)
        data = [0x59, 0x59, 0x23, 6] if busy_write else [0x1F, 0x1A, 0x2F, 7]
        for i, v in enumerate(data):
            p.byte(0xF068 + i, v)
        p.byte(0xF06C, 0xC8)
        p.code += bytes.fromhex("6a08f068e88047f8")  # wait for busy entry
        if busy_write:
            p.byte(0xF068, 0x12)
            p.code += bytes.fromhex("6a08f0686a88f800")
        p.code += bytes.fromhex("6a08f068e88046f8")  # wait for pending commit
        for i, a in enumerate([0xF068, 0xF069, 0xF06A, 0xF06B, 0xF067]):
            p.code += bytes((0x6A, 8, a >> 8, a & 255, 0x6A, 0x88, 0xF8, i + 1))
        expected = "92000000007f" if busy_write else "00101a2f0707"
        name = (
            "rtc-calendar-busy-write"
            if busy_write
            else "rtc-calendar-raw-digits-and-alias"
        )
        yield Case(
            name,
            p.finish(),
            {"ram": {"f800": expected}},
            None,
            evidence=basis,
            milliseconds=1100,
        )

    basis = RTC_EVIDENCE
    p = Program()
    p.byte(0xF06F, 0x18)
    p.byte(0xFFC0, 2)
    p.code += bytes.fromhex(
        "6a08ffd4e80146f86a88f8006a08ffd4e80147f86a88f8016a08f06c6a88f802"
    )
    yield Case(
        "rtc-clock-output-with-run-clear",
        p.finish(),
        {"ram": {"f800": "000100"}},
        None,
        evidence=basis,
    )

    basis = {
        "kind": "documented",
        "source": "REJ09B0152-0300 §§10.4.3,10.6",
        "question": "Does a rising capture record a stopped counter and request vector 35?",
    }
    p = Program()
    p.byte(0xFFFB, 0x44)
    p.byte(0xFFE4, 7)
    p.byte(0xFFD4, 4)
    p.word(0xF0F6, 0x1234)
    p.byte(0xF0F4, 0x8C)
    p.byte(0xF0F2, 1)
    p.byte(0xFFD4, 5)
    p.code += bytes.fromhex("067f018040fc")
    image = handler(p.finish(), 35, "6b00f0f86b80f7806a08f0f3f8006a88f0f35670")
    yield Case(
        "timer-w-gpio-capture",
        image,
        {"ram": {"f780": "1234"}, "interrupt_entries": 1},
        None,
        evidence=basis,
    )

    basis = {
        "kind": "documented",
        "source": "REJ09B0152-0300 §§13.3–13.5",
        "question": "Do actual package inputs produce the specified AEC count/gate interrupt?",
    }
    for gate_irq in [False, True]:
        p = Program()
        for a, v in [
            (0xFFFB, 12),
            (0xFFC0, 8),
            (0xFFC0, 0x28),
            (0xFF92, 0x10),
            (0xFF95, 0x17),
            (0xFFF3 if gate_irq else 0xFFF4, 4 if gate_irq else 1),
        ]:
            p.byte(a, v)
        p.code += bytes.fromhex("067f018040fc")
        isr = "f8016a88f7802895f8173895f80038" + ("f6" if gate_irq else "f7") + "5670"
        image = handler(p.finish(), 18 if gate_irq else 32, isr)
        rows = ["0,digital,p11,0", "0,digital,p12,1"]
        if gate_irq:
            rows += ["100,digital,p12,0"]
        else:
            for i in range(256):
                rows += [
                    f"{100 + 10 * i},digital,p11,1",
                    f"{105 + 10 * i},digital,p11,0",
                ]
        yield Case(
            "aec-gate-interrupt" if gate_irq else "aec-external-overflow",
            image,
            {"ram": {"f780": "01"}, "interrupt_entries": 1},
            "\n".join(rows) + "\n",
            evidence=basis,
        )
