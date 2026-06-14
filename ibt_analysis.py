"""Turn a parsed `.ibt` session into tidy tables + pace stats.

Field results come from the SessionInfo YAML (whole field). Your own per-lap
times and the best-lap telemetry trace are derived from the telemetry channels
(only the player's car is logged). Telemetry lap/result times are already in
seconds (unlike the web API's ten-thousandths).
"""
import pandas as pd

MPS_TO_KMH = 3.6
RAD_TO_DEG = 57.29577951308232
TRACE_POINTS = 250  # downsample target for the best-lap trace


def format_time(seconds) -> str:
    """Seconds -> 'M:SS.mmm' (blank when missing/invalid)."""
    if seconds is None or seconds < 0:
        return ""
    minutes = int(seconds // 60)
    return f"{minutes}:{seconds - minutes * 60:06.3f}"


def _clean_time(value):
    """iRacing uses -1 (and sometimes huge sentinels) for 'no time'."""
    if value is None or value < 0:
        return None
    return float(value)


# --- field results (from SessionInfo) --------------------------------------

def _drivers_by_idx(session_info: dict) -> dict:
    drivers = (session_info.get("DriverInfo") or {}).get("Drivers") or []
    return {d.get("CarIdx"): d for d in drivers}


def race_session(session_info: dict) -> dict:
    """The Race session block (falls back to the last session)."""
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


# --- per-lap timing (from telemetry) ---------------------------------------

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


def my_laps_df(session) -> pd.DataFrame:
    laps = session.channel("Lap")
    times = session.channel("SessionTime")
    if not laps or not times:
        return pd.DataFrame()

    speed = session.channel("Speed")
    on_pit = session.channel("OnPitRoad")
    segs = _segments(laps)

    rows = []
    for k, (lap_no, start, end) in enumerate(segs):
        if lap_no is None or lap_no < 1:
            continue  # grid / out-of-session
        # Lap time = time between this lap's start and the next lap's start.
        if k + 1 >= len(segs):
            continue  # final lap is incomplete (no following crossing)
        secs = times[segs[k + 1][1]] - times[start]
        pitted = bool(any(on_pit[start:end])) if on_pit else False
        max_kmh = max(speed[start:end]) * MPS_TO_KMH if speed else None
        rows.append({
            "Lap": lap_no,
            "Lap Time": format_time(secs),
            "Seconds": round(secs, 3),
            "On Pit": pitted,
            "Max kph": round(max_kmh, 1) if max_kmh is not None else None,
            "Clean": secs > 0 and not pitted,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.sort_values("Lap").reset_index(drop=True)
    clean = df.loc[df["Clean"], "Seconds"]
    best = clean.min() if not clean.empty else None
    df["Δ Best"] = (df["Seconds"] - best).round(3) if best is not None else None
    return df


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
    """Lap number of the fastest clean lap (or None)."""
    if df.empty:
        return None
    clean = df.loc[df["Clean"]]
    if clean.empty:
        return None
    return int(clean.loc[clean["Seconds"].idxmin(), "Lap"])


# --- best-lap telemetry trace ----------------------------------------------

def best_lap_trace_df(session, lap_number) -> pd.DataFrame:
    """Downsampled Speed/Throttle/Brake/Gear/Steering vs lap distance for one lap."""
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

    idxs = range(start, end)
    stride = max(1, len(idxs) // TRACE_POINTS)
    rows = []
    for i in list(idxs)[::stride]:
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


def summary_rows(session_info: dict, stats: dict, best_lap, laps_df) -> list:
    week = session_info.get("WeekendInfo") or {}
    race = race_session(session_info)
    player = _player(session_info)
    player_idx = (session_info.get("DriverInfo") or {}).get("DriverCarIdx")

    track = week.get("TrackDisplayName") or week.get("TrackName")
    if week.get("TrackConfigName"):
        track = f"{track} – {week['TrackConfigName']}"

    rows = [
        ["Field", "Value"],
        ["Track", track],
        ["Car", player.get("CarScreenName")],
        ["Session", race.get("SessionType")],
        ["Subsession", week.get("SubSessionID")],
        ["Driver", player.get("UserName")],
        ["iRating", player.get("IRating")],
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
            ["Result best lap", format_time(_clean_time(my_result.get("FastestTime")))],
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
    return rows
