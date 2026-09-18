"""RTC calendar transitions, busy reads and clock output."""

from diagnostic import Case

from .h8 import Program

RTC_EVIDENCE = {
    "kind": "documented",
    "source": "REJ09B0152-0300 §§8.1.4,11.3–11.5; REJ06B0514 RCS=1xxx table",
    "question": "Do calendar updates preserve a pending busy update, and does "
    "TMOW drive P10 independently of RUN?",
}


def cases():
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
            evidence=basis
            if busy_write
            else {
                "kind": "software_reasoned",
                "source": RTC_EVIDENCE["source"],
                "question": "How do malformed calendar digits carry, and what does the RTCDR alias expose?",
                "limitation": "Malformed digits follow inferred counter carry rules; this expectation has no hardware capture.",
            },
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
        "source": "REJ09B0152-0300 §§11.3.1–11.3.6,11.4.3,11.5; figure 11.2",
        "question": "Do carries update the calendar and AM/PM correctly, with enabled flags "
        "appearing during or after busy as selected by INT?",
    }
    # Seconds, minutes, hours, weekday; PM is separate in RTCCR1.
    transitions = [
        ("second", 0x40, "58341202", "59341202", 0x40, 0x04),
        ("minute", 0x40, "59341202", "00351202", 0x40, 0x0C),
        ("hour", 0x40, "59590902", "00001002", 0x40, 0x1C),
        ("midnight-24", 0x40, "59592302", "00000003", 0x40, 0x3C),
        ("week-24", 0x40, "59592306", "00000000", 0x40, 0x7C),
        ("noon-12", 0, "59591102", "00000002", 0x20, 0x1C),
        ("midnight-12", 0x20, "59591102", "00000003", 0, 0x3C),
        ("week-12", 0x20, "59591106", "00000000", 0, 0x7C),
    ]
    for name, mode, before, after, next_mode, flags in transitions:
        for timing in (0, 8):
            p = Program()
            p.byte(0xFFB1, 0x12)
            p.byte(0xFFB1, 0xA2)  # disable the watchdog for the one-second wait
            p.byte(0xF06C, 0x10)
            p.byte(0xF06C, 0)
            p.byte(0xF06D, 0x7C)  # enable calendar flags; leave subsecond flags off
            for i, value in enumerate(bytes.fromhex(before)):
                p.byte(0xF068 + i, value)
            p.byte(0xF06C, 0x80 | mode | timing)
            p.code += bytes.fromhex("6a08f068e88047f8")  # wait for busy
            if timing == 0:
                p.code += bytes.fromhex("6a08f067e80447f8")  # flag while busy
            p.code += bytes.fromhex("6a08f068e8806a88f8006a08f0676a88f801")
            p.code += bytes.fromhex("6a08f068e88046f8")  # wait for stable data
            for i, address in enumerate(
                [0xF068, 0xF069, 0xF06A, 0xF06B, 0xF06C, 0xF067]
            ):
                p.code += bytes(
                    (0x6A, 8, address >> 8, address & 255, 0x6A, 0x88, 0xF8, i + 2)
                )
            expected = bytes([0x80, flags if timing == 0 else 0])
            expected += bytes.fromhex(after) + bytes([0x80 | next_mode | timing, flags])
            yield Case(
                f"rtc-{name}-{'after' if timing else 'during'}-busy",
                p.finish(),
                {"ram": {"f800": expected.hex()}},
                evidence=basis,
                milliseconds=1100,
            )
