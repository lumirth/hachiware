"""Human-readable report of a results.json."""

from __future__ import annotations


def fraction(entry: dict) -> str:
    if not entry["features"]:
        return "-"
    return f"{entry['conformant']}/{entry['features']}"


def report(results: dict, failing: int = 12) -> None:
    names = list(results["targets"])
    scores = results.get("scores", {})
    print(f"hachiware benchmark, seed {results['seed']}")
    for name in names:
        caps = results["targets"][name]
        changed = " (SOURCES CHANGED DURING RUN)" if caps.get("sources_changed") else ""
        print(f"  {name}: {' '.join(caps['command'])}{changed}")
        for kind, what in caps.get("capabilities", {}).get("assists", {}).items():
            print(f"    adapter assists {kind}: {what}")

    conf = scores.get("conformance")
    if conf:
        print("\nConformance: features whose every case passes")
        width = max(len(n) for n in names) + 2
        print(f"  {'':<{width}}{'documented':>12}{'+inferred':>12}{'conditional':>13}"
              f"{'firmware-used':>15}{'beyond':>9}")
        for name in names:
            s = conf[name]
            d = s["documented"]
            print(f"  {name:<{width}}{fraction(d):>12}{fraction(s['with_inferred']):>12}"
                  f"{fraction(s['conditional']):>13}{fraction(d['firmware_used']):>15}"
                  f"{fraction(d['beyond_firmware']):>9}")
        print("\n  Cases passed:")
        for name in names:
            counts = conf[name]["cases"]
            cells = [f"{grade} {c['pass']}/{c['total']}"
                     + (f" ({c['not_applicable']} n/a)" if c["not_applicable"] else "")
                     for grade, c in sorted(counts.items())]
            print(f"  {name:<{width}}" + "; ".join(cells))
        blocks = sorted({b for name in names for b in conf[name]["with_inferred"]["blocks"]})
        print("\n  By block (documented + inferred cases):")
        print("  " + f"{'':<16}" + "".join(f"{n:>{max(12, len(n) + 2)}}" for n in names))
        for block in blocks:
            cells = []
            for n in names:
                entry = conf[n]["with_inferred"]["blocks"].get(block)
                cells.append(f"{fraction(entry) if entry else '-':>{max(12, len(n) + 2)}}")
            print(f"  {block:<16}" + "".join(cells))
        for name in names:
            bad = conf[name]["with_inferred"]["failing"]
            if bad:
                print(f"\n  {name}: {len(bad)} features not conformant"
                      + (f" (first {failing})" if len(bad) > failing else ""))
                for entry in bad[:failing]:
                    shown = ", ".join(entry["failed"][:3])
                    more = f" +{len(entry['failed']) - 3}" if len(entry["failed"]) > 3 else ""
                    print(f"    {entry['block']}: {entry['feature']} "
                          f"[{len(entry['failed'])}/{entry['cases']} cases: {shown}{more}]")

    rows = results.get("workloads") or []
    if rows:
        workloads(rows, names, scores.get("speed"))
    audit = results.get("audit")
    if audit is not None:
        print("\nDiscrimination audit:")
        if not any(audit.values()):
            print("  every case and workload failed its controls")
        for name, findings in audit.items():
            for f in findings:
                print(f"  {name}: {f.get('case') or f.get('workload')}: "
                      f"{f.get('reason', 'check passed')} with {f['control']}")


def verdict(result: dict) -> str:
    if "x_realtime" not in result:
        return result["status"].upper()
    if result["status"] != "accurate":
        return "FAILED"
    return "assisted" if result.get("assisted") else "ok"


def marks(result: dict) -> str:
    return "".join(m for m, key in (("*", "short_horizon"), ("~", "noisy"), ("w", "waiting"))
                   if result.get(key))


def speed_cell(result: dict) -> str:
    if "x_realtime" not in result:
        return "-"
    return f"{result['x_realtime']['wall']:.1f}" + marks(result)


def figure(entry: dict | None, kind: str, counts: dict) -> str:
    if entry is None:
        if counts["untimed"]:
            return f"n/a ({len(counts['untimed'])} untimed)"
        return "-"
    value = entry[kind]
    if value is not None:
        text = f"{value:.1f}"
        if kind == "measured":
            text += f" ({counts['verified_workloads']}/{counts['workloads']} ok)"
        return text
    return f"withheld ({counts['verified_workloads']}/{counts['workloads']} ok)"


def workloads(rows: list[dict], names: list[str], speed: dict | None) -> None:
    width = max(len(r["workload"]) for r in rows) + 2
    col = max(22, max(len(n) for n in names) + 4)
    print("\nWorkloads: speed (x realtime, wall clock) | checks")
    print("  ok: every run passed every check. FAILED: the emulator ran the workload")
    print("  wrongly, so its speed is for different behavior. assisted: correct, but the")
    print("  adapter did part of the hardware's work. Marks: * horizon too short,")
    print("  ~ samples spread over 25%, w process busy under 90% of wall time.")
    for tier in ("use", "hardware"):
        members = [r for r in rows if r["tier"] == tier]
        if not members:
            continue
        print(f"\n  {tier} tier")
        print(f"  {'':<{width}}" + "".join(f"{n:>{col}}" for n in names))
        for row in members:
            cells = []
            for name in names:
                r = row["targets"][name]
                cells.append(f"{speed_cell(r) + ' | ' + verdict(r):>{col}}")
            print(f"  {row['workload']:<{width}}" + "".join(cells))
    print("\n  Host time per work unit:")
    for row in rows:
        for name in names:
            units = row["targets"][name].get("ns_per_unit")
            if units:
                text = ", ".join(f"{v / 1e6:.3g} ms/{singular(u)}" if v >= 1e5
                                 else f"{v:.3g} ns/{singular(u)}" for u, v in units.items())
                print(f"    {row['workload']:<{width}}{name:<{col - 8}}{text}")
    failures = [(name, row["workload"], row["targets"][name]["failures"][0])
                for row in rows for name in names
                if row["targets"][name]["status"] != "accurate"
                and row["targets"][name]["failures"]]
    if failures:
        print("\n  First failed check per workload:")
        for name, workload, failure in failures:
            print(f"    {name} {workload}: {failure}")
    if not speed:
        return
    headline(speed, names, col)
    for pair in speed["pairwise"]:
        head_to_head(pair, width)


def singular(unit: str) -> str:
    return {"batches": "batch", "presses": "press"}.get(unit, unit.removesuffix("s"))


def headline(speed: dict, names: list[str], col: int) -> None:
    profile = speed["day_profile"]
    total = sum(profile.values())
    shares = ", ".join(f"{w} {s / 3600:.3g} h" for w, s in profile.items())
    print("\nHeadline figures (x realtime)")
    print(f"  day profile ({total / 3600:.0f} h): {shares}")
    print("  floor: slowest use workload; hardware: geometric mean of hardware workloads")
    print("  verified: all passed without assistance; measured: all timed workloads")
    print(f"  {'':<20}" + "".join(f"{n:>{col}}" for n in names))
    rows = []
    for kind in ("verified", "measured"):
        rows.append((f"day {kind}", lambda t, k=kind: figure(t["use"]["day"], k, t["use"])))
    for kind in ("verified", "measured"):
        rows.append((f"floor {kind}", lambda t, k=kind: figure(t["use"]["floor"], k, t["use"])))
    for kind in ("verified", "measured"):
        rows.append((f"hardware {kind}",
                     lambda t, k=kind: figure(t["hardware"] if t["hardware"]["measured"]
                                              is not None or t["hardware"]["untimed"]
                                              else None, k, t["hardware"])))
    for label, cell in rows:
        print(f"  {label:<20}" + "".join(f"{cell(speed['targets'][n]):>{col}}" for n in names))
    sensitivity(speed, names, col)
    floors = [f"{n}: {speed['targets'][n]['use']['floor']['workload']}" for n in names
              if speed["targets"][n]["use"].get("floor")]
    if floors:
        print("  slowest use scenario: " + ", ".join(floors))
    for n in names:
        day = speed["targets"][n]["use"].get("day")
        if day and day["covered_seconds"] != total:
            print(f"  {n}: day covers {day['covered_seconds'] / 3600:.3g} h of the profile "
                  "(only the use workloads run)")
        bad = speed["targets"][n]["use"]
        for label, key in (("failed checks", "failed_checks"), ("assisted", "assisted")):
            items = bad.get(key, []) + speed["targets"][n]["hardware"].get(key, [])
            if items:
                print(f"  {n} {label}: {', '.join(items)}")


def sensitivity(speed: dict, names: list[str], col: int) -> None:
    """Show how the day figure moves under other plausible day splits."""
    alts = speed.get("alternate_profiles")
    if not alts:
        return
    print("\n  Day figure under other plausible day splits (measured, x realtime):")
    print(f"  {'profile':<16}" + "".join(f"{n:>{col}}" for n in names))
    def row(label, getter):
        cells = []
        for n in names:
            value = getter(n)
            cells.append(f"{value:.1f}" if value is not None else "-")
        print(f"  {label:<16}" + "".join(f"{c:>{col}}" for c in cells))
    row("as weighted", lambda n: (speed["targets"][n]["use"].get("day") or {}).get("measured"))
    for label in alts:
        row(label, lambda n, l=label: ((speed["targets"][n]["use"].get("day") or {})
                                       .get("alternates", {}).get(l)))
    hours = {label: sum(prof.values()) / 3600 for label, prof in alts.items()}
    detail = "; ".join(
        f"{label}: " + ", ".join(f"{w} {sec / 3600:.3g} h" for w, sec in prof.items())
        for label, prof in alts.items())
    print(f"  splits ({detail})")


def head_to_head(pair: dict, width: int) -> None:
    a, b = pair["a"], pair["b"]
    total = len(pair["workloads"])
    print(f"\nHead to head: {a} vs {b} (ratio = {a} speed / {b} speed; "
          f">1 means {a} is faster)")
    cw = max(12, len(a) + 2, len(b) + 2)
    print(f"  {'':<{width}}{a:>{cw}}{b:>{cw}}{'ratio':>9}   checks ({a} / {b})")
    for w in pair["workloads"]:
        print(f"  {w['workload']:<{width}}{w['a_x']:>{cw}.1f}{w['b_x']:>{cw}.1f}"
              f"{w['ratio']:>8.2f}x   {w['a_status']} / {w['b_status']}")
    # Measured head-to-head: always shown, over every workload both ran. Speed
    # only; where a target's behaviour differed the ratio is not equal work.
    print("\n  Measured figures (every workload both ran, speed only):")
    for label, key, names_key in (
            ("day", "measured_day_ratio", "measured_day_workloads"),
            ("floor", "measured_floor_ratio", "measured_day_workloads"),
            ("hardware", "measured_hardware_ratio", "measured_hardware_workloads")):
        if pair[key] is not None:
            over = ", ".join(pair[names_key]) if pair[names_key] else ""
            print(f"    {label:<9}{pair[key]:>6.2f}x   over {over}")
    # How much and what kind of work differed, so a measured ratio is never
    # mistaken for equal work.
    for name, differs, assisted in ((a, pair["a_differs"], pair["a_assisted"]),
                                    (b, pair["b_differs"], pair["b_assisted"])):
        if differs:
            failed = [w for w in differs if w not in assisted]
            parts = []
            if failed:
                parts.append(f"failed checks on {len(failed)} ({', '.join(failed)})")
            if assisted:
                parts.append(f"was adapter-assisted on {len(assisted)} ({', '.join(assisted)})")
            print(f"    {name} differs on {len(differs)} of {total}: " + "; ".join(parts))
    # Verified head-to-head: equal, correct, unassisted work only.
    print(f"\n  Verified figures (equal correct work: {pair['equal_work']} of {total}):")
    if pair["day_ratio"] is not None:
        print(f"    day      {pair['day_ratio']:>6.2f}x   over {', '.join(pair['day_workloads'])}")
    if pair["floor_ratio"] is not None:
        print(f"    floor    {pair['floor_ratio']:>6.2f}x   over the same")
    if pair["hardware_ratio"] is not None:
        print(f"    hardware {pair['hardware_ratio']:>6.2f}x   "
              f"over {', '.join(pair['hardware_workloads'])}")
    if not pair["equal_work"]:
        print("    No shared passing, unassisted workloads.")
