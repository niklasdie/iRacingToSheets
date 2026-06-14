"""Stint detection/analytics and session-type classification for endurance runs.

A *stint* is the run of laps between pit stops (typically one tank). Stints are
split at detected pit stops (see ibt_analysis.detect_stops); each stop carries
its fuel delta and duration, so refuels and long service/driver-change stops are
distinguished. The session is also auto-classified (qualifying vs race/endurance
vs long run) so the right analytics are produced.
"""
import numpy as np
import pandas as pd

from ibt_analysis import format_time

DRIVER_CHANGE_MIN_S = 45.0   # stops at/above this are flagged as possible driver swaps
REFUEL_MIN_L = 1.0           # fuel added above this counts as a real refuel


# --- helpers ----------------------------------------------------------------

def _deg_slope(seconds: list):
    """Lap-time trend over a stint (s/lap): + = fading, - = building pace."""
    vals = [s for s in seconds if s is not None]
    if len(vals) < 3:
        return None
    return float(np.polyfit(np.arange(len(vals)), vals, 1)[0])


def _player_name(session_info: dict):
    di = session_info.get("DriverInfo") or {}
    drivers = {d.get("CarIdx"): d for d in (di.get("Drivers") or [])}
    return (drivers.get(di.get("DriverCarIdx")) or {}).get("UserName")


def is_team_session(session_info: dict) -> bool:
    """More than one driver registered on the player's car => team/endurance."""
    di = session_info.get("DriverInfo") or {}
    me = di.get("DriverCarIdx")
    mine = [d for d in (di.get("Drivers") or []) if d.get("CarIdx") == me]
    return len(mine) > 1


def stop_label(stop: dict, team: bool) -> str:
    if not stop:
        return ""
    dur = stop.get("duration") or 0
    added = stop.get("fuel_added")
    bits = [f"{dur:.0f}s"]
    if added is not None and added > REFUEL_MIN_L:
        bits.append(f"+{added:.0f}L")
    elif added is not None and added <= REFUEL_MIN_L:
        bits.append("splash")
    if dur >= DRIVER_CHANGE_MIN_S and team:
        bits.append("driver change?")
    return ", ".join(bits)


# --- stint table ------------------------------------------------------------

def stint_table(lap_df: pd.DataFrame, stops: list, session_info: dict) -> pd.DataFrame:
    if lap_df.empty:
        return pd.DataFrame()
    driver = _player_name(session_info)
    team = is_team_session(session_info)
    rows = []
    for sid in sorted(lap_df["Stint"].unique()):
        s = lap_df[lap_df["Stint"] == sid]
        green = s[s["Clean"]]
        secs = green["Seconds"].dropna().tolist()
        used = s["Fuel Used"].dropna()
        green_used = green["Fuel Used"].dropna()
        starting_stop = stops[sid - 2] if (sid >= 2 and sid - 2 < len(stops)) else None
        ending_stop = stops[sid - 1] if (sid - 1 < len(stops)) else None
        duration = s["Seconds"].dropna().sum()
        rows.append({
            "Stint": int(sid),
            "Driver": driver,
            "Laps": int(len(s)),
            "Green": int(len(green)),
            "Duration": format_time(duration) if duration > 0 else "",
            "Best": format_time(min(secs)) if secs else "",
            "Avg": format_time(float(np.mean(secs))) if secs else "",
            "Median": format_time(float(np.median(secs))) if secs else "",
            "Std s": round(float(np.std(secs, ddof=1)), 3) if len(secs) > 1 else (0.0 if secs else None),
            "Deg s/lap": round(_deg_slope(secs), 3) if _deg_slope(secs) is not None else None,
            "Fuel Used L": round(float(used.sum()), 2) if not used.empty else None,
            "Fuel/Lap L": round(float(green_used.median()), 2) if not green_used.empty else None,
            "Refuel L": round(starting_stop["fuel_added"], 1)
                if (starting_stop and starting_stop.get("fuel_added") is not None) else None,
            "Pit After": stop_label(ending_stop, team),
            "Inc": int(s["Inc"].dropna().sum()) if not s["Inc"].dropna().empty else None,
        })
    return pd.DataFrame(rows)


# --- session classification -------------------------------------------------

def _session_type_label(session) -> str:
    """SessionType from SessionInfo for the session most of the samples are in."""
    info = session.session_info
    sessions = (info.get("SessionInfo") or {}).get("Sessions") or []
    nums = session.channel("SessionNum")
    num = max(set(nums), key=nums.count) if nums else None
    chosen = next((s for s in sessions if s.get("SessionNum") == num), None)
    if chosen is None and sessions:
        chosen = next((s for s in sessions if str(s.get("SessionType", "")).upper() == "RACE"), sessions[-1])
    return (chosen or {}).get("SessionType") or ""


def classify_session(session, lap_df: pd.DataFrame, stops: list):
    """Return (detected_type, reason). Uses the session label plus heuristics
    (lap count, pit stops, refuelling) so a 'qual sim' run in practice is still
    recognised."""
    label = _session_type_label(session).strip()
    up = label.upper()
    n_laps = len(lap_df)
    n_clean = int(lap_df["Clean"].sum()) if not lap_df.empty else 0
    refueled = any((s.get("fuel_added") or 0) > REFUEL_MIN_L for s in stops)
    n_stops = len(stops)

    if "QUAL" in up:
        return "Qualifying", f"session type '{label}'"
    if n_stops >= 1 or refueled or n_laps >= 20:
        why = []
        if n_stops:
            why.append(f"{n_stops} pit stop(s)")
        if refueled:
            why.append("refuelled")
        if n_laps >= 20:
            why.append(f"{n_laps} laps")
        return "Endurance", "; ".join(why)
    if n_clean <= 4 and n_laps <= 6:
        return "Qualifying (inferred)", f"only {n_clean} flying lap(s), no pit stops"
    if "RACE" in up:
        return "Race", f"session type '{label}'"
    return "Long run / practice", f"{n_laps} laps, no pit stops"


def qualifying_summary(lap_df: pd.DataFrame) -> list:
    rows = [["Field", "Value"]]
    if lap_df.empty:
        return rows
    flying = lap_df[lap_df["Clean"]].sort_values("Seconds")
    rows.append(["Flying laps", int(len(flying))])
    if not flying.empty:
        best = flying.iloc[0]
        rows += [["Best lap", best["Lap Time"]], ["Best lap #", int(best["Lap"])]]
        for _, r in flying.iterrows():
            delta = r["Δ Best"]
            gap = f"  (+{delta:.3f})" if (pd.notna(delta) and delta > 0) else ""
            rows.append([f"Lap {int(r['Lap'])}", f"{r['Lap Time']}{gap}"])
    fuel_start = lap_df["Fuel Start"].dropna()
    if not fuel_start.empty:
        rows.append(["Fuel at start (L)", round(float(fuel_start.iloc[0]), 1)])
    used = lap_df["Fuel Used"].dropna().sum()
    if used:
        rows.append(["Fuel used (L)", round(float(used), 1)])
    return rows
