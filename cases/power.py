"""Supply interruptions, reset timing and volatile memory retention."""

from diagnostic import Case
from .h8 import Program


def cases():
    basis = {
        "kind": "software_reasoned",
        "source": "REJ09B0152-0300 §§19.2,21.2; RAM retention Table21.2; original constant-rail circuit "
        "calculation",
        "question": "Do short and sustained rail collapses distinguish stopped execution, RC reset, and "
        "retained or lost volatile data?",
        "limitation": "The configured reset circuit and retention exposure model determine the expected reset and RAM contents.",
        "physical_device": "power-interruption fixture; preserve user nonvolatile data separately",
    }
    conditions = {
        "reset_resistance_ohms": 100000,
        "reset_capacitance_nf": 100,
        "reset_threshold_vcc_fraction": 0.8,
        "ram_retention_floor_mv": 1500,
        "ram_retention_exposure_mv_ms": 15000,
    }
    # Entry count lives in retained RAM. These physical conditions distinguish
    # a paused CPU, RES re-entry with retained RAM, and volatile charge loss.
    for name, absence, expected in [
        ("short-retention", 1000, 1),
        ("reset-retention", 5000, 2),
        ("long-collapse", 20000, 1),
    ]:
        p = Program()
        p.code += bytes.fromhex("6a08f8000a086a88f800")
        p.byte(0xF801, 0xA5)
        yield Case(
            "power-" + name,
            p.finish(),
            {"ram": {"f800": f"{expected:02x}a5"}},
            f"100,supply,0\n{100 + absence},supply,3000\n",
            evidence=basis,
            milliseconds=50,
            conditions=conditions,
        )
    for mv, duration in [(0, 10000), (1000, 30000)]:
        for delta, expected in [(-1000, "a5"), (1000, "00")]:
            p = Program()
            p.byte(0xF800, 0xA5)
            # Observe while still below execution voltage; no reboot rewrites RAM.
            elapsed = duration + delta
            yield Case(
                f"power-retention-{mv}-{elapsed}",
                p.finish(),
                {"ram": {"f800": expected}},
                f"{50000 - elapsed},supply,{mv}\n",
                evidence=basis,
                milliseconds=50,
                conditions=conditions,
            )
