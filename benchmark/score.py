"""Scores from raw results: feature conformance and verified speed.

Speed has two tiers that answer different questions and are never blended:

- use: how fast the Pokéwalker runs as it is used. Its headline is the day
  figure, the emulated seconds of a stated day profile over the host seconds
  they take (a time-weighted harmonic mean, because a day's host time is the
  sum of its modes' host times), and the floor, the slowest use scenario,
  which bounds whether every mode runs in real time.
- hardware: how fast each block runs at full load. Workloads weigh equally
  in a geometric mean; no share of use exists for microbenchmarks.

Every figure is given twice. measured covers every timed workload, correct or
not. verified exists only when every workload in the figure passed all of its
checks without adapter assistance, so skipping work, being wrong quickly or
letting the adapter do the hardware's work cannot raise it.
"""

from __future__ import annotations

import math

from . import coverage

# Seconds of a day spent in each use scenario, grounded in the decomp and
# ordinary use. A Pokewalker is carried all waking day and left on a table
# overnight; the firmware keeps running MainTick/CaptureSample the whole time
# (lumirth/pw MainTick: the motion tick runs in every mode that is not an
# active IR session), so carry dominates. The screen only draws in interactive
# mode and powers off on its own: INTERACTIVE_DISPLAY_SECONDS is 60 s and
# INPUT_DISPLAY_SECONDS 90 s per glance (pw_power.h), so a day of glances and a
# few menu sessions is minutes, not hours. IR runs only while two devices face
# each other; a daily sync plus occasional gifts/peer play is on that order.
# The split below is one defensible day; it is an assumption, not a measurement,
# so every per-scenario speed is reported and ALTERNATE_PROFILES shows how much
# the day figure moves under other plausible splits.
#   carry      23 h 10 min  carried and resting, MainTick the whole time
#   watch-face     20 min   ~20 screen-on glances at the animated home screen
#   menu           10 min   button-driven menu sessions
#   ir-sync        10 min   established syncs: a daily sync, gifts and peer play
#   ir-probe        6 min   connecting: CONNECT probing and retries before a sync
#   buzzer          4 min   jingles and alert tones played on the piezo buzzer
DAY_PROFILE = {"carry": 83_400, "watch-face": 1_200, "menu": 600, "ir-sync": 600,
               "ir-probe": 360, "buzzer": 240}
DAY = sum(DAY_PROFILE.values())

# Plausible alternative day splits, to show the day figure's sensitivity to the
# weighting. Scenarios absent from a target's run are dropped from its day.
ALTERNATE_PROFILES = {
    # A device barely touched: almost all carry, a glance or two.
    "mostly-carried": {"carry": 85_200, "watch-face": 480, "menu": 180, "ir-sync": 240,
                       "ir-probe": 180, "buzzer": 120},
    # A heavy-use day: many glances, menu diving, several syncs and connects.
    "social-heavy": {"carry": 78_000, "watch-face": 3_000, "menu": 1_800, "ir-sync": 2_400,
                     "ir-probe": 900, "buzzer": 300},
    # Every use scenario weighted equally, ignoring how a day is actually spent.
    "equal-time": {"carry": 14_400, "watch-face": 14_400, "menu": 14_400, "ir-sync": 14_400,
                   "ir-probe": 14_400, "buzzer": 14_400},
}


def geomean(values: list[float]) -> float:
    return math.exp(sum(math.log(v) for v in values) / len(values))


def timed(row: dict, name: str) -> bool:
    return "x_realtime" in row["targets"].get(name, {})


def verified(row: dict, name: str) -> bool:
    return timed(row, name) and row["targets"][name]["verified"]


def wall(row: dict, name: str) -> float:
    return row["targets"][name]["x_realtime"]["wall"]


def day_speed(speeds: dict[str, float], profile: dict[str, int] = DAY_PROFILE) -> tuple[float, int]:
    """Emulated seconds over host seconds for the profile's scenarios present."""
    present = {w: s for w, s in profile.items() if w in speeds}
    if not present:
        return None, 0
    host = sum(s / speeds[w] for w, s in present.items())
    return sum(present.values()) / host, sum(present.values())


def status(rows: list[dict], name: str) -> dict:
    untimed = [r["workload"] for r in rows if not timed(r, name)]
    failed = [r["workload"] for r in rows if timed(r, name)
              and r["targets"][name]["status"] != "accurate"]
    assisted = [r["workload"] for r in rows if timed(r, name)
                and r["targets"][name].get("assisted")]
    ok = len(rows) - len(untimed) - len({*failed, *assisted})
    return {"workloads": len(rows), "verified_workloads": ok, "untimed": untimed,
            "failed_checks": failed, "assisted": assisted}


def use_figures(rows: list[dict], name: str) -> dict:
    out = status(rows, name)
    if not rows or out["untimed"]:
        return out | {"day": None, "floor": None}
    speeds = {r["workload"]: wall(r, name) for r in rows}
    day, covered = day_speed(speeds) if set(speeds) & set(DAY_PROFILE) else (None, 0)
    slowest = min(speeds, key=speeds.get)
    clean = out["verified_workloads"] == len(rows)
    alternates = {label: day_speed(speeds, prof)[0]
                  for label, prof in ALTERNATE_PROFILES.items()}
    return out | {
        "speeds": speeds,
        "day": {"measured": day, "verified": day if clean else None,
                "covered_seconds": covered, "profile": DAY_PROFILE,
                "alternates": alternates},
        "floor": {"measured": speeds[slowest], "verified": speeds[slowest] if clean else None,
                  "workload": slowest},
    }


def hardware_figures(rows: list[dict], name: str) -> dict:
    out = status(rows, name)
    if not rows or out["untimed"]:
        return out | {"measured": None, "verified": None}
    value = geomean([wall(r, name) for r in rows])
    return out | {"measured": value,
                  "verified": value if out["verified_workloads"] == len(rows) else None}


def pairwise(rows: list[dict], a: str, b: str) -> dict:
    rows_ab = [r for r in rows if timed(r, a) and timed(r, b)]
    entry = {"a": a, "b": b, "workloads": []}
    for r in rows_ab:
        entry["workloads"].append({
            "workload": r["workload"], "tier": r["tier"],
            "a_x": wall(r, a), "b_x": wall(r, b), "ratio": wall(r, a) / wall(r, b),
            "a_verified": verified(r, a), "b_verified": verified(r, b),
            "a_status": cell_status(r["targets"][a]), "b_status": cell_status(r["targets"][b])})
    rated = entry["workloads"]
    use_all = [w for w in rated if w["tier"] == "use"]
    hw_all = [w for w in rated if w["tier"] == "hardware"]
    both = [w for w in rated if w["a_verified"] and w["b_verified"]]
    use = [w for w in both if w["tier"] == "use"]
    hardware = [w for w in both if w["tier"] == "hardware"]
    entry["equal_work"] = len(both)
    # Verified ratios: equal, correct, unassisted work only.
    entry["day_ratio"] = ratios_day(use, "a_x", "b_x")
    entry["day_workloads"] = [w["workload"] for w in use]
    entry["floor_ratio"] = (min(w["a_x"] for w in use) / min(w["b_x"] for w in use)
                            if use else None)
    entry["hardware_ratio"] = geomean([w["ratio"] for w in hardware]) if hardware else None
    entry["hardware_workloads"] = [w["workload"] for w in hardware]
    # Measured ratios: every workload both targets ran, regardless of whether
    # the behaviour matched. Always present when both timed the workload, and
    # labelled with how work differed so the comparison is never silently lost.
    entry["measured_day_ratio"] = ratios_day(use_all, "a_x", "b_x")
    entry["measured_day_workloads"] = [w["workload"] for w in use_all]
    entry["measured_floor_ratio"] = (min(w["a_x"] for w in use_all)
                                     / min(w["b_x"] for w in use_all) if use_all else None)
    entry["measured_hardware_ratio"] = (geomean([w["ratio"] for w in hw_all])
                                       if hw_all else None)
    entry["measured_hardware_workloads"] = [w["workload"] for w in hw_all]
    entry["a_differs"] = [w["workload"] for w in rated if w["a_status"] != "ok"]
    entry["b_differs"] = [w["workload"] for w in rated if w["b_status"] != "ok"]
    entry["a_assisted"] = [w["workload"] for w in rated if w["a_status"] == "assisted"]
    entry["b_assisted"] = [w["workload"] for w in rated if w["b_status"] == "assisted"]
    return entry


def ratios_day(workloads: list[dict], a_key: str, b_key: str):
    """Day-figure ratio over the day-profile workloads in a list, or None."""
    if not any(w["workload"] in DAY_PROFILE for w in workloads):
        return None
    a = day_speed({w["workload"]: w[a_key] for w in workloads})[0]
    b = day_speed({w["workload"]: w[b_key] for w in workloads})[0]
    return a / b if a and b else None


def cell_status(result: dict) -> str:
    if "x_realtime" not in result:
        return result["status"]
    if result["status"] != "accurate":
        return "failed"
    return "assisted" if result.get("assisted") else "ok"


def speed(rows: list[dict], names: list[str]) -> dict:
    use = [r for r in rows if r["tier"] == "use"]
    hardware = [r for r in rows if r["tier"] == "hardware"]
    out = {"day_profile": DAY_PROFILE, "alternate_profiles": ALTERNATE_PROFILES,
           "targets": {}, "pairwise": []}
    for name in names:
        out["targets"][name] = {"use": use_figures(use, name),
                                "hardware": hardware_figures(hardware, name)}
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            out["pairwise"].append(pairwise(rows, a, b))
    return out


def score(results: dict) -> dict:
    names = list(results["targets"])
    scores = {}
    if "conformance" in results:
        cases = {c["name"]: c for c in results["cases"]}
        scores["conformance"] = {name: coverage.conformance_score(results["conformance"][name],
                                                                   cases)
                                 for name in names}
    if results.get("workloads"):
        scores["speed"] = speed(results["workloads"], names)
    return scores
