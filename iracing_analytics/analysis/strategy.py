"""Fuel-to-finish and pit-window strategy projection.

From the session's measured fuel burn (L/lap), green-lap pace, tank capacity and
race length, project: laps per tank, fuel needed to finish, minimum pit stops,
and a pit *window* (earliest/latest lap) plus suggested fill for each stop.

Race length is taken from the file when it's a real race, or supplied via
--race-laps / --race-minutes (handy for projecting an upcoming race from a
practice run). Tank capacity comes from DriverInfo (DriverCarFuelMaxLtr ×
DriverCarMaxFuelPct), falling back to the most fuel seen in the file.
"""
import math

import pandas as pd

from .laps import format_time, race_session

DEFAULT_MARGIN_LAPS = 0.3   # safety fuel kept in reserve, expressed in laps
DEFAULT_PIT_LOSS_S = 30.0   # assumed time lost per stop (timed-race lap estimate)
_UNLIMITED = 1.0e6          # telemetry sentinel for "no limit"


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_limit(value):
    """SessionLaps/SessionTime -> number, or None for 'unlimited'/blank/0."""
    if value is None:
        return None
    s = str(value).strip().lower()
    if not s or "unlimit" in s or s == "0":
        return None
    return _num(s)


def usable_tank(session):
    """(usable_litres, capacity_litres, max_pct) from DriverInfo, or fuel seen."""
    di = session.session_info.get("DriverInfo") or {}
    cap = _num(di.get("DriverCarFuelMaxLtr"))
    pct = _num(di.get("DriverCarMaxFuelPct"))
    if cap:
        if pct and 0 < pct <= 1:
            return cap * pct, cap, pct
        return cap, cap, 1.0
    fuel = session.channel("FuelLevel")
    if fuel:
        return max(fuel), max(fuel), None
    return None, None, None


def fuel_basis(lap_df, stats):
    """(burn L/lap from clean laps, avg green lap seconds)."""
    burn = None
    if not lap_df.empty:
        med = lap_df.loc[lap_df["Clean"], "Fuel Used"].median()
        burn = float(med) if pd.notna(med) else None
    avg = stats.get("median") or stats.get("average")
    return burn, avg


def race_definition(session, race_laps, race_minutes):
    """Resolve (race_laps, race_time_s, source). CLI overrides the file."""
    if race_laps:
        return int(race_laps), None, "override (--race-laps)"
    if race_minutes:
        return None, float(race_minutes) * 60.0, "override (--race-minutes)"

    rs = race_session(session.session_info)
    laps = _parse_limit(rs.get("SessionLaps"))
    time = _parse_limit(rs.get("SessionTime"))
    if laps:
        return int(laps), None, "session"
    if time:
        return None, float(time), "session"

    lt = session.channel("SessionLapsTotal")
    if lt and 0 < lt[-1] < 32767:
        return int(lt[-1]), None, "telemetry"
    tt = session.channel("SessionTimeTotal")
    if tt and 0 < tt[-1] < _UNLIMITED:
        return None, float(tt[-1]), "telemetry"
    return None, None, None


def project(session, lap_df, stats, race_laps, race_minutes,
            margin_laps=DEFAULT_MARGIN_LAPS, pit_loss_s=DEFAULT_PIT_LOSS_S) -> list:
    rows = [["Field", "Value"]]
    burn, avg = fuel_basis(lap_df, stats)
    if not burn or not avg:
        rows.append(["(not enough clean-lap fuel/pace data to project)", ""])
        return rows

    usable, cap, pct = usable_tank(session)
    rows.append(["Fuel burn (L/lap)", round(burn, 2)])
    rows.append(["Avg green lap", format_time(avg)])

    stint_laps = None
    if usable:
        cap_txt = f"{usable:.1f} L"
        if pct and pct < 1:
            cap_txt += f"  (cap {cap:.0f} L × {pct * 100:.0f}%)"
        rows.append(["Usable tank", cap_txt])
        stint_laps = max(1, math.floor((usable - margin_laps * burn) / burn))
        rows.append(["Stint length (laps/tank)", f"{stint_laps}  (~{format_time(stint_laps * avg)})"])

    fuel = session.channel("FuelLevel")
    if fuel:
        rows.append(["Fuel at end of data (L)", round(fuel[-1], 1)])
        rows.append(["Laps left in that tank", round(fuel[-1] / burn, 1)])

    laps, race_time, source = race_definition(session, race_laps, race_minutes)
    approx = False
    if laps is None and race_time is not None:
        # Convert a timed race to laps, correcting for time lost in the pits.
        est = race_time / avg
        for _ in range(3):
            s_tmp = max(0, math.ceil(est / stint_laps) - 1) if stint_laps else 0
            est = (race_time - s_tmp * pit_loss_s) / avg
        laps = max(1, round(est))
        approx = True

    rows.append(["", ""])
    if not laps:
        rows.append(["Race projection",
                     "set --race-laps N or --race-minutes M (or RACE_LAPS in .env)"])
        return rows
    if not stint_laps:
        rows.append(["Race projection", "tank capacity unknown — cannot size stints"])
        return rows

    head = source + (f" — ~{laps} laps from {int(race_time / 60)} min (approx)" if approx else "")
    rows.append(["--- Race projection ---", head])
    if not approx:
        rows.append(["Race length (laps)", laps])
    rows.append(["Fuel to finish (L)",
                 f"{laps * burn + margin_laps * burn:.1f}  (incl. {margin_laps:.1f}-lap reserve)"])

    stops = max(0, math.ceil(laps / stint_laps) - 1)
    rows.append(["Minimum pit stops", stops])
    if stops == 0:
        rows.append(["Strategy", f"no-stop — {laps} laps fits one tank (max {stint_laps})"])
        return rows

    n_stints = stops + 1
    base, rem = divmod(laps, n_stints)
    stint_lengths = [base + (1 if i < rem else 0) for i in range(n_stints)]
    pit_lap = 0
    for k in range(stops):
        pit_lap += stint_lengths[k]
        latest = min(laps - 1, (k + 1) * stint_laps)
        earliest = max(1, laps - (stops - k) * stint_laps)
        fill = stint_lengths[k + 1] * burn + margin_laps * burn
        rows.append([f"Stop {k + 1}: target lap {pit_lap}",
                     f"window L{earliest}–{latest}, add ~{fill:.0f} L"])
    return rows
