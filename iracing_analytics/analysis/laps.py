"""Turn a parsed `.ibt` session into tidy tables + pace stats.

Field results come from the SessionInfo YAML (whole field). Your own per-lap
data, stints, and the best-lap telemetry trace are derived from the telemetry
channels (only the player's car is logged). Telemetry lap/result times are
already in seconds (unlike the web API's ten-thousandths).
"""
import numpy as np
import pandas as pd

MPS_TO_KMH = 3.6
RAD_TO_DEG = 57.29577951308232
TRACE_POINTS = 250          # downsample target for the best-lap trace
PIT_STOP_MIN_S = 1.0        # ignore pit-road blips shorter than this
PIT_STATIONARY_MPS = 2.0    # "stopped in pit" speed threshold (fallback)


def format_time(seconds) -> str:
    """Seconds -> 'M:SS.mmm' (blank when missing/invalid)."""
    if seconds is None or (isinstance(seconds, float) and np.isnan(seconds)) or seconds < 0:
        return ""
    minutes = int(seconds // 60)
    return f"{minutes}:{seconds - minutes * 60:06.3f}"


def _clean_time(value):
    if value is None or value < 0:
        return None
    return float(value)


# --- field results (from SessionInfo) --------------------------------------

def _drivers_by_idx(session_info: dict) -> dict:
    drivers = (session_info.get("DriverInfo") or {}).get("Drivers") or []
    return {d.get("CarIdx"): d for d in drivers}


def race_session(session_info: dict) -> dict:
    sessions = (session_info.get("SessionInfo") or {}).get("Sessions") or []
    for s in sessions:
        if str(s.get("SessionType", "")).upper() == "RACE":
            return s
    return sessions[-1] if sessions else {}


def field_results_df(session_info: dict) -> pd.DataFrame:
    drivers = _drivers_by_idx(session_info)
    race = race_session(session_info)
    rows = []
    for r in race.get("ResultsPositions") or []:
        d = drivers.get(r.get("CarIdx"), {})
        rows.append({
            "Pos": r.get("Position"),
            "Driver": d.get("UserName"),
            "Car #": d.get("CarNumber"),
            "Car": d.get("CarScreenName"),
            "Best Lap": format_time(_clean_time(r.get("FastestTime"))),
            "Last Lap": format_time(_clean_time(r.get("LastTime"))),
            "Laps": r.get("LapsComplete"),
            "Inc": r.get("Incidents"),
            "iRating": d.get("IRating"),
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("Pos", na_position="last").reset_index(drop=True)
    return df


# --- pit stops + per-lap table (from telemetry) ----------------------------

def _segments(laps: list):
    """Contiguous (lap_number, start_idx, end_idx_exclusive) runs."""
    segs, i, n = [], 0, len(laps)
    while i < n:
        j = i
        while j < n and laps[j] == laps[i]:
            j += 1
        segs.append((laps[i], i, j))
        i = j
    return segs


def detect_stops(session) -> list:
    """Detect pit stops as runs stationary in the pit box.

    Uses PlayerCarInPitStall when present, else OnPitRoad + near-zero speed.
    Each stop records two durations so it's clear where the time went:
      • ``duration``     – standing time only (stationary in the box)
      • ``pit_duration`` – full pit-lane time, from entering to leaving pit road
                           (i.e. the limiter-on window around the stop); the slow
                           in/out laps are ``pit_duration - duration``.
    Plus the fuel added across it, so refuels and long service/driver-change
    stops can be told apart. ``pit_duration`` is None if OnPitRoad is unavailable.
    """
    t = session.channel("SessionTime")
    if not t:
        return []
    stall = session.channel("PlayerCarInPitStall")
    on_pit = session.channel("OnPitRoad")
    speed = session.channel("Speed")
    fuel = session.channel("FuelLevel")
    lap = session.channel("Lap")
    n = len(t)

    def stationary(k):
        if stall:
            return bool(stall[k])
        if on_pit and speed:
            return bool(on_pit[k]) and speed[k] < PIT_STATIONARY_MPS
        return False

    stops, k = [], 0
    while k < n:
        if stationary(k):
            a = k
            while k < n and stationary(k):
                k += 1
            b = k - 1
            duration = t[b] - t[a]
            if duration >= PIT_STOP_MIN_S:
                before = fuel[a - 1] if (fuel and a > 0) else (fuel[a] if fuel else None)
                after = fuel[b + 1] if (fuel and b + 1 < n) else (fuel[b] if fuel else None)
                added = (after - before) if (after is not None and before is not None) else None
                # Widen to the pit-road (limiter-on) window bracketing the stop:
                # back to where OnPitRoad became true, forward to where it ends.
                pit_duration = None
                if on_pit:
                    entry, leave = a, b
                    while entry > 0 and bool(on_pit[entry - 1]):
                        entry -= 1
                    while leave + 1 < n and bool(on_pit[leave + 1]):
                        leave += 1
                    pit_duration = t[leave] - t[entry]
                stops.append({
                    "start": a, "end": b, "lap": lap[a] if lap else None,
                    "duration": duration, "pit_duration": pit_duration,
                    "fuel_before": before,
                    "fuel_after": after, "fuel_added": added,
                })
        else:
            k += 1
    return stops


def lap_table(session) -> pd.DataFrame:
    """Rich per-lap table: timing, fuel, incidents, pit flags, and stint id."""
    lap = session.channel("Lap")
    t = session.channel("SessionTime")
    if not lap or not t:
        return pd.DataFrame()
    on_pit = session.channel("OnPitRoad")
    fuel = session.channel("FuelLevel")
    speed = session.channel("Speed")
    inc = session.channel("PlayerCarMyIncidentCount")
    stop_ends = sorted(s["end"] for s in detect_stops(session))

    segs = _segments(lap)
    rows = []
    for k, (lap_no, start, end) in enumerate(segs):
        if lap_no is None or lap_no < 1:
            continue
        complete = k + 1 < len(segs)
        secs = (t[segs[k + 1][1]] - t[start]) if complete else None
        f_start = fuel[start] if fuel else None
        f_end = fuel[end - 1] if fuel else None
        used = (f_start - f_end) if (f_start is not None and f_end is not None and f_start >= f_end) else None
        rows.append({
            "Lap": lap_no,
            "Stint": 1 + sum(1 for e in stop_ends if e < start),
            "Lap Time": format_time(secs),
            "Seconds": round(secs, 3) if secs is not None else None,
            "Fuel Start": round(f_start, 2) if f_start is not None else None,
            "Fuel End": round(f_end, 2) if f_end is not None else None,
            "Fuel Used": round(used, 2) if used is not None else None,
            "Max kph": round(max(speed[start:end]) * MPS_TO_KMH, 1) if speed else None,
            "Inc": int(inc[end - 1] - inc[start]) if inc else None,
            "Out": bool(on_pit[start]) if on_pit else False,
            "In": bool(on_pit[end - 1]) if on_pit else False,
            "Pit": bool(any(on_pit[start:end])) if on_pit else False,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.sort_values("Lap").reset_index(drop=True)
    # The first lap of each stint is an out-lap (race start or post-pit).
    df.loc[df.groupby("Stint").head(1).index, "Out"] = True
    df["In"] = df["In"] & ~df["Out"]
    df["Clean"] = (
        df["Seconds"].notna() & ~df["Out"] & ~df["In"] & ~df["Pit"] & (df["Seconds"] > 0)
    )
    clean = df.loc[df["Clean"], "Seconds"]
    best = clean.min() if not clean.empty else None
    df["Δ Best"] = (df["Seconds"] - best).round(3) if best is not None else None
    return df


def laps_view(df: pd.DataFrame) -> pd.DataFrame:
    """Friendly per-lap columns for the 'My Laps' tab, with a lap-type label."""
    if df.empty:
        return df
    kind = np.where(df["Out"], "out",
            np.where(df["In"], "in",
             np.where(df["Pit"], "pit",
              np.where(df["Clean"], "green", "lap"))))
    view = df[["Lap", "Stint", "Lap Time", "Seconds", "Δ Best",
               "Fuel Used", "Max kph", "Inc"]].copy()
    view.insert(3, "Type", kind)
    return view


def lap_stats(df: pd.DataFrame) -> dict:
    if df.empty:
        return {}
    clean = df.loc[df["Clean"], "Seconds"].dropna()
    stats = {"total_laps": int(len(df)), "clean_laps": int(len(clean))}
    if not clean.empty:
        best = clean.min()
        stats.update({
            "best": best,
            "average": clean.mean(),
            "median": clean.median(),
            "std": clean.std() if len(clean) > 1 else 0.0,
            "within_101pct": int((clean <= best * 1.01).sum()),
        })
    return stats


def best_clean_lap(df: pd.DataFrame):
    if df.empty:
        return None
    clean = df.loc[df["Clean"]]
    if clean.empty:
        return None
    return int(clean.loc[clean["Seconds"].idxmin(), "Lap"])


# --- best-lap telemetry trace ----------------------------------------------

def best_lap_trace_df(session, lap_number) -> pd.DataFrame:
    if lap_number is None:
        return pd.DataFrame()
    laps = session.channel("Lap")
    if not laps:
        return pd.DataFrame()
    seg = next((s for s in _segments(laps) if s[0] == lap_number), None)
    if not seg:
        return pd.DataFrame()
    start, end = seg[1], seg[2]

    dist = session.channel("LapDistPct")
    speed = session.channel("Speed")
    throttle = session.channel("Throttle")
    brake = session.channel("Brake")
    gear = session.channel("Gear")
    steer = session.channel("SteeringWheelAngle")

    idxs = list(range(start, end))
    stride = max(1, len(idxs) // TRACE_POINTS)
    rows = []
    for i in idxs[::stride]:
        rows.append({
            "Lap Dist %": round(dist[i] * 100, 2) if dist else None,
            "Speed kph": round(speed[i] * MPS_TO_KMH, 1) if speed else None,
            "Throttle %": round(throttle[i] * 100, 1) if throttle else None,
            "Brake %": round(brake[i] * 100, 1) if brake else None,
            "Gear": gear[i] if gear else None,
            "Steering °": round(steer[i] * RAD_TO_DEG, 1) if steer else None,
        })
    return pd.DataFrame(rows)


# --- summary ----------------------------------------------------------------

def _player(session_info: dict) -> dict:
    return _drivers_by_idx(session_info).get(
        (session_info.get("DriverInfo") or {}).get("DriverCarIdx"), {}
    )


def build_title(session_info: dict) -> str:
    week = session_info.get("WeekendInfo") or {}
    track = week.get("TrackDisplayName") or week.get("TrackName") or "Unknown Track"
    car = _player(session_info).get("CarScreenName") or "iRacing"
    return f"iRacing — {car} @ {track}"


def summary_rows(session_info: dict, stats: dict, best_lap, lap_df, detected: str, n_stops: int) -> list:
    week = session_info.get("WeekendInfo") or {}
    race = race_session(session_info)
    player = _player(session_info)
    player_idx = (session_info.get("DriverInfo") or {}).get("DriverCarIdx")

    track = week.get("TrackDisplayName") or week.get("TrackName")
    if week.get("TrackConfigName"):
        track = f"{track} – {week['TrackConfigName']}"

    rows = [
        ["Field", "Value"],
        ["Session type (detected)", detected],
        ["Track", track],
        ["Car", player.get("CarScreenName")],
        ["Subsession", week.get("SubSessionID")],
        ["Driver", player.get("UserName")],
        ["iRating", player.get("IRating")],
        ["Pit stops", n_stops],
    ]

    my_result = next(
        (r for r in (race.get("ResultsPositions") or []) if r.get("CarIdx") == player_idx),
        None,
    )
    if my_result:
        rows += [
            ["Finish", my_result.get("Position")],
            ["Laps", my_result.get("LapsComplete")],
            ["Incidents", my_result.get("Incidents")],
        ]

    if stats:
        rows += [
            ["", ""],
            ["--- Your pace (clean laps) ---", ""],
            ["Clean / total laps", f"{stats.get('clean_laps', 0)} / {stats.get('total_laps', 0)}"],
            ["Best lap", format_time(stats.get("best"))],
            ["Best lap #", best_lap],
            ["Average", format_time(stats.get("average"))],
            ["Median", format_time(stats.get("median"))],
            ["Consistency (std)", f"{stats.get('std', 0):.3f}s" if "std" in stats else ""],
            ["Laps within 101%", stats.get("within_101pct")],
        ]
        if not lap_df.empty:
            fuel_per_lap = lap_df.loc[lap_df["Clean"], "Fuel Used"].median()
            if pd.notna(fuel_per_lap):
                rows.append(["Fuel / lap (L)", round(fuel_per_lap, 2)])
    return rows
