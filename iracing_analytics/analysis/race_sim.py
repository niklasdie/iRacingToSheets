"""Full-race simulation / strategy optimiser.

Endurance prep rarely allows running the whole race, so this extrapolates a full
race from a short practice/stint in the `.ibt`: it takes the measured fresh-tyre
pace, per-stint **degradation**, **fuel burn** and tank size, then simulates a
race of an adjustable length. It compares strategies (different pit-stop counts)
and recommends one, reporting stops, stint plan, target lap times, fuel and time.

Model (deliberately simple and transparent):
  • lap i of a stint = fresh_pace + degradation * i   (tyres assumed changed each stop)
  • a stint is capped by fuel (and optionally a max stint time / driver limit)
  • each stop costs a fixed pit-loss in time
Assumes steady running (no safety cars, traffic, weather, or fuel-save) — it's a
planning baseline, not a guarantee.
"""
import math

import numpy as np

from .laps import format_time
from . import strategy

SC_PACE_FACTOR = 1.6   # a lap under safety car takes ~1.6× a green lap


def _clock(seconds) -> str:
    seconds = int(round(seconds))
    h, m, s = seconds // 3600, (seconds % 3600) // 60, seconds % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def base_pace(lap_df, stats):
    clean = lap_df.loc[lap_df["Clean"], "Seconds"].dropna() if not lap_df.empty else []
    if len(clean):
        return float(clean.min())
    return stats.get("best") or stats.get("median")


def deg_estimate(lap_df) -> float:
    """Median per-stint lap-time slope (s/lap) across green laps."""
    slopes = []
    if lap_df.empty:
        return 0.0
    for _, s in lap_df[lap_df["Clean"]].groupby("Stint"):
        secs = s.sort_values("Lap")["Seconds"].dropna().tolist()
        if len(secs) >= 3:
            slopes.append(float(np.polyfit(range(len(secs)), secs, 1)[0]))
    return float(np.median(slopes)) if slopes else 0.0


def _stint_time(laps, p0, deg):
    return laps * p0 + deg * laps * (laps - 1) / 2.0


def _sim_timed(total_s, p0, deg, pit_loss, stint_laps):
    """Run fixed-length stints until the clock expires. Returns (laps, stints)."""
    t, laps, stints = 0.0, 0, []
    while True:
        run = 0
        for i in range(stint_laps):
            t += p0 + deg * i
            laps += 1
            run += 1
            if t >= total_s:
                stints.append(run)
                return laps, stints
        stints.append(run)
        t += pit_loss
        if t >= total_s:
            return laps, stints


def _timed_candidates(total_s, p0, deg, burn, stint_cap, pit_loss):
    avg_full = p0 + deg * max(0, stint_cap - 1) / 2.0
    r_est = total_s / avg_full
    s_min = max(0, math.ceil(r_est / stint_cap) - 1)
    out, seen = [], set()
    for stops in range(s_min, s_min + 5):
        stint_laps = min(stint_cap, max(1, round(r_est / (stops + 1))))
        laps, stints = _sim_timed(total_s, p0, deg, pit_loss, stint_laps)
        actual_stops = len(stints) - 1
        if actual_stops in seen:
            continue
        seen.add(actual_stops)
        out.append({"stops": actual_stops, "stint_laps": stint_laps, "laps": laps,
                    "avg": total_s / laps, "fuel": laps * burn,
                    "pit": actual_stops * pit_loss, "stints": stints})
    out.sort(key=lambda c: c["stops"])
    return out


def _lap_candidates(race_laps, p0, deg, burn, stint_cap, pit_loss):
    s_min = max(0, math.ceil(race_laps / stint_cap) - 1)
    out = []
    for stops in range(s_min, s_min + 5):
        n = stops + 1
        base, rem = divmod(race_laps, n)
        stints = [base + (1 if i < rem else 0) for i in range(n)]
        if not stints or min(stints) <= 0 or max(stints) > stint_cap:
            continue
        total = sum(_stint_time(L, p0, deg) for L in stints) + stops * pit_loss
        out.append({"stops": stops, "stint_laps": max(stints), "laps": race_laps,
                    "avg": total / race_laps, "fuel": race_laps * burn,
                    "pit": stops * pit_loss, "finish": total, "stints": stints})
    return out


def _plan_rows(best, p0, deg, burn, timed, drivers):
    rows = [["", ""]]
    headline = (f"{best['stops']} stop(s) → {best['laps']} laps" if timed
               else f"{best['stops']} stop(s) → {_clock(best['finish'])}")
    rows.append(["Recommended", headline])
    rows.append(["Stint plan", "laps | first → last lap | fuel"])
    for k, L in enumerate(best["stints"]):
        last = p0 + deg * max(0, L - 1)
        rows.append([f"Stint {k + 1}", f"{L} laps | {format_time(p0)} → {format_time(last)} | {L * burn:.0f} L"])
    if drivers:
        rows.append(["Drivers", f"{drivers} → ~{len(best['stints']) / drivers:.1f} stints each"])
    return rows


def simulate(session, lap_df, stats, params) -> list:
    rows = [["Field", "Value"]]
    p0 = base_pace(lap_df, stats)
    burn, _ = strategy.fuel_basis(lap_df, stats)
    if not p0 or not burn:
        return rows + [["(not enough clean-lap data to simulate a race)", ""]]
    usable, cap, pct = strategy.usable_tank(session)
    if not usable:
        return rows + [["(tank capacity unknown — cannot simulate stints)", ""]]

    deg = params["deg"] if params.get("deg") is not None else max(0.0, deg_estimate(lap_df))
    p0_fresh = p0 + (params.get("pace_offset") or 0.0)   # car pace, clean air
    traffic = params.get("traffic") or 0.0
    p0 = p0_fresh + traffic                              # green pace used by the sim
    margin = params.get("margin_laps", 0.3)
    pit_loss = params.get("pit_loss", 30.0)
    fuel_cap = max(1, math.floor((usable - margin * burn) / burn))
    stint_cap = fuel_cap
    if params.get("max_stint_minutes"):
        avg_guess = p0 + deg * max(0, fuel_cap - 1) / 2.0
        stint_cap = max(1, min(fuel_cap, math.floor(params["max_stint_minutes"] * 60 / avg_guess)))

    # Resolve race length: CLI/.env override, else the file's own race.
    if params.get("race_minutes"):
        race_t, race_laps, src = params["race_minutes"] * 60.0, None, "override"
    elif params.get("race_laps"):
        race_t, race_laps, src = None, int(params["race_laps"]), "override"
    else:
        race_laps, race_t, src = strategy.race_definition(session, None, None)

    rows += [
        ["Race length", (f"{_clock(race_t)} (timed)" if race_t else (f"{race_laps} laps" if race_laps else "—"))],
        ["Source", src],
        ["Fresh-tyre pace", format_time(p0_fresh)],
        ["Degradation", f"+{deg:.3f} s/lap ({'set' if params.get('deg') is not None else 'measured'})"],
        ["Fuel burn", f"{burn:.2f} L/lap"],
        ["Usable tank", f"{usable:.0f} L → max {fuel_cap} laps/stint"],
    ]
    if stint_cap < fuel_cap:
        rows.append(["Stint cap", f"{stint_cap} laps (≤ {params['max_stint_minutes']} min)"])
    if params.get("pace_offset"):
        rows.append(["Pace offset", f"{params['pace_offset']:+.2f} s/lap"])
    if traffic:
        rows.append(["Traffic", f"+{traffic:.2f} s/lap → green pace {format_time(p0)}"])
    rows.append(["Pit loss / stop", f"{pit_loss:.0f} s"])

    if not race_t and not race_laps:
        return rows + [["", ""],
                       ["Race sim", "set --race-hours H (or --race-minutes / --race-laps)"]]

    rows.append(["", ""])
    if race_t:
        cands = _timed_candidates(race_t, p0, deg, burn, stint_cap, pit_loss)
        best = max(cands, key=lambda c: c["laps"])
        rows.append(["Strategy comparison", "(more laps = better)"])
        rows.append(["Stops", "Stint laps", "Total laps", "Avg lap", "Fuel L", ""])
        for c in cands:
            rows.append([c["stops"], c["stint_laps"], c["laps"], format_time(c["avg"]),
                         round(c["fuel"]), "  ← most laps" if c is best else ""])
    else:
        cands = _lap_candidates(race_laps, p0, deg, burn, stint_cap, pit_loss)
        best = min(cands, key=lambda c: c["finish"])
        rows.append(["Strategy comparison", "(less time = better)"])
        rows.append(["Stops", "Stint laps", "Avg lap", "Fuel L", "Pit time", "Finish"])
        for c in cands:
            rows.append([c["stops"], c["stint_laps"], format_time(c["avg"]), round(c["fuel"]),
                         _clock(c["pit"]), _clock(c["finish"]) + ("  ← fastest" if c is best else "")])

    rows += _plan_rows(best, p0, deg, burn, bool(race_t), params.get("drivers"))

    # --- traffic & safety-car sensitivity ---
    max_k = max(3, int(params.get("safety_cars") or 0))
    sc_dur = (params.get("sc_minutes") or 5.0) * 60.0
    discount = params.get("sc_pit_discount", 0.4)
    if race_t:
        rows += _traffic_rows_timed(race_t, p0_fresh, traffic, deg, pit_loss, best)
        rows += _sc_rows_timed(race_t, p0, p0_fresh, deg, pit_loss, best, sc_dur, discount, max_k)
    else:
        rows += _traffic_rows_laps(p0_fresh, traffic, deg, pit_loss, best)
        rows += _sc_rows_laps(best, p0_fresh, pit_loss, sc_dur, discount, max_k)
    return rows


def _traffic_levels(traffic):
    return sorted({round(traffic, 2), round(traffic + 0.25, 2), round(traffic + 0.5, 2)})


def _traffic_rows_timed(race_t, p0_fresh, traffic, deg, pit_loss, best):
    rows = [["", ""], ["Traffic sensitivity", "laps completed at green-pace traffic levels"],
            ["Traffic +s/lap", "Total laps", "vs first", ""]]
    base = None
    for i, lv in enumerate(_traffic_levels(traffic)):
        laps, _ = _sim_timed(race_t, p0_fresh + lv, deg, pit_loss, best["stint_laps"])
        base = laps if i == 0 else base
        now = " (now)" if abs(lv - traffic) < 1e-9 else ""
        rows.append([f"+{lv:.2f}{now}", laps, "—" if i == 0 else f"{laps - base:+d}", ""])
    return rows


def _traffic_rows_laps(p0_fresh, traffic, deg, pit_loss, best):
    rows = [["", ""], ["Traffic sensitivity", "finish time at traffic levels"],
            ["Traffic +s/lap", "Finish", "vs first", ""]]
    base = None
    for i, lv in enumerate(_traffic_levels(traffic)):
        total = sum(_stint_time(L, p0_fresh + lv, deg) for L in best["stints"]) + best["stops"] * pit_loss
        base = total if i == 0 else base
        now = " (now)" if abs(lv - traffic) < 1e-9 else ""
        rows.append([f"+{lv:.2f}{now}", _clock(total), "—" if i == 0 else f"+{_clock(total - base)}", ""])
    return rows


def _sc_rows_timed(race_t, p0_green, p0_fresh, deg, pit_loss, best, sc_dur, discount, max_k):
    rows = [["", ""],
            ["Safety-car sensitivity", f"each ~{sc_dur / 60:.0f} min; pit under yellow pays {discount * 100:.0f}% of normal loss"],
            ["Safety cars", "Total laps", "vs 0 SC", "Pit time saved"]]
    sc_lap = p0_fresh * SC_PACE_FACTOR
    base = None
    for k in range(max_k + 1):
        sc_time = k * sc_dur
        saved = min(k, best["stops"]) * (1 - discount) * pit_loss
        green_laps, _ = _sim_timed(max(0.0, race_t - sc_time) + saved, p0_green, deg, pit_loss, best["stint_laps"])
        total = green_laps + (int(sc_time / sc_lap) if sc_lap > 0 else 0)
        base = total if k == 0 else base
        rows.append([k, total, "—" if k == 0 else f"{total - base:+d}", f"{saved:.0f}s"])
    return rows


def _sc_rows_laps(best, p0_fresh, pit_loss, sc_dur, discount, max_k):
    rows = [["", ""],
            ["Safety-car sensitivity", f"each ~{sc_dur / 60:.0f} min; pit under yellow pays {discount * 100:.0f}% of normal loss"],
            ["Safety cars", "Finish time", "vs 0 SC", "Pit time saved"]]
    added = sc_dur * (1 - best["avg"] / (p0_fresh * SC_PACE_FACTOR))  # extra time per SC vs green
    base = best["finish"]
    for k in range(max_k + 1):
        saved = min(k, best["stops"]) * (1 - discount) * pit_loss
        finish = best["finish"] + k * added - saved
        delta = "—" if k == 0 else f"{'+' if finish >= base else '-'}{_clock(abs(finish - base))}"
        rows.append([k, _clock(finish), delta, f"{saved:.0f}s"])
    return rows
