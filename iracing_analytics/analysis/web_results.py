"""Turn raw iRacing result/lap JSON into tidy tables and pace stats.

iRacing reports lap times as integers in ten-thousandths of a second
(e.g. 905000 == 90.5s). -1 means "no time" (pit/out lap/incident).
"""
import pandas as pd

TEN_THOUSANDTHS = 10000.0
# Lap events that mean the lap isn't a representative flying lap.
_DIRTY_EVENT_HINTS = ("pit", "off", "tow", "black")


def to_seconds(value) -> float | None:
    """iRacing lap-time int -> seconds, or None when there is no valid time."""
    if value is None or value < 0:
        return None
    return value / TEN_THOUSANDTHS


def format_time(seconds: float | None) -> str:
    """Seconds -> 'M:SS.mmm' (blank when there is no time)."""
    if seconds is None:
        return ""
    minutes = int(seconds // 60)
    return f"{minutes}:{seconds - minutes * 60:06.3f}"


def _ir_delta(row: dict) -> int | str:
    old, new = row.get("oldi_rating"), row.get("newi_rating")
    if old is None or new is None or old < 0 or new < 0:
        return ""
    return new - old


def pick_race_simsession(result: dict) -> dict:
    """The RACE sim-session (falls back to the last one if unnamed)."""
    sims = result.get("session_results", []) or []
    for sim in sims:
        if str(sim.get("simsession_name", "")).upper() == "RACE":
            return sim
    return sims[-1] if sims else {}


def driver_row(simsession: dict, cust_id: int) -> dict | None:
    for r in simsession.get("results", []) or []:
        if r.get("cust_id") == cust_id:
            return r
    return None


def field_results_df(simsession: dict) -> pd.DataFrame:
    rows = []
    for r in simsession.get("results", []) or []:
        livery = r.get("livery") or {}
        rows.append({
            "Pos": (r.get("finish_position", -1) or 0) + 1,
            "Driver": r.get("display_name"),
            "Car": r.get("car_name"),
            "Car #": livery.get("car_number") or r.get("car_number"),
            "Best Lap": format_time(to_seconds(r.get("best_lap_time", -1))),
            "Avg Lap": format_time(to_seconds(r.get("average_lap", -1))),
            "Laps": r.get("laps_complete"),
            "Inc": r.get("incidents"),
            "Start": (r.get("starting_position", -1) or 0) + 1,
            "iR Δ": _ir_delta(r),
            "Club": r.get("club_name"),
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("Pos").reset_index(drop=True)
    return df


def my_laps_df(laps: list, cust_id: int) -> pd.DataFrame:
    rows = []
    for lap in laps or []:
        if lap.get("cust_id") != cust_id:
            continue
        events = lap.get("lap_events") or []
        secs = to_seconds(lap.get("lap_time", -1))
        dirty = any(hint in e.lower() for e in events for hint in _DIRTY_EVENT_HINTS)
        rows.append({
            "Lap": lap.get("lap_number"),
            "Lap Time": format_time(secs),
            "Seconds": round(secs, 3) if secs is not None else None,
            "Incident": bool(lap.get("incident")),
            "Clean": secs is not None and not lap.get("incident") and not dirty,
            "Events": ", ".join(events),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.sort_values("Lap").reset_index(drop=True)

    clean = df.loc[df["Clean"], "Seconds"]
    best = clean.min() if not clean.empty else None
    df["Δ Best"] = (
        (df["Seconds"] - best).round(3) if best is not None else None
    )
    return df


def lap_stats(df: pd.DataFrame) -> dict:
    """Pace summary computed from the clean flying laps."""
    if df.empty:
        return {}
    clean = df.loc[df["Clean"], "Seconds"].dropna()
    stats = {
        "total_laps": int(len(df)),
        "clean_laps": int(len(clean)),
        "incident_laps": int(df["Incident"].sum()),
    }
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


def build_title(result: dict) -> str:
    track = (result.get("track") or {}).get("track_name", "Unknown Track")
    series = result.get("series_name") or result.get("season_name") or "iRacing"
    date = (result.get("start_time") or "")[:10]
    return f"iRacing — {series} @ {track} ({date})".strip()


def summary_rows(result: dict, simsession: dict, cust_id: int | None, stats: dict) -> list:
    track = result.get("track") or {}
    track_name = track.get("track_name", "")
    if track.get("config_name"):
        track_name = f"{track_name} – {track['config_name']}"

    rows = [
        ["Field", "Value"],
        ["Series", result.get("series_name") or result.get("season_name")],
        ["Track", track_name],
        ["Date", result.get("start_time")],
        ["Subsession", result.get("subsession_id")],
        ["Strength of Field", result.get("event_strength_of_field")],
        ["Cautions", result.get("num_cautions")],
        ["Caution laps", result.get("num_caution_laps")],
        ["Lead changes", result.get("num_lead_changes")],
    ]

    me = driver_row(simsession, cust_id) if cust_id else None
    if me:
        rows += [
            ["", ""],
            ["--- Your result ---", ""],
            ["Driver", me.get("display_name")],
            ["Finish", (me.get("finish_position", -1) or 0) + 1],
            ["Start", (me.get("starting_position", -1) or 0) + 1],
            ["Best lap", format_time(to_seconds(me.get("best_lap_time", -1)))],
            ["Avg lap", format_time(to_seconds(me.get("average_lap", -1)))],
            ["Incidents", me.get("incidents")],
            ["iR change", _ir_delta(me)],
        ]

    if stats:
        rows += [
            ["", ""],
            ["--- Your pace (clean laps) ---", ""],
            ["Clean / total laps", f"{stats.get('clean_laps', 0)} / {stats.get('total_laps', 0)}"],
            ["Best", format_time(stats.get("best"))],
            ["Average", format_time(stats.get("average"))],
            ["Median", format_time(stats.get("median"))],
            ["Consistency (std)", f"{stats.get('std', 0):.3f}s" if "std" in stats else ""],
            ["Laps within 101% of best", stats.get("within_101pct")],
            ["Incident laps", stats.get("incident_laps")],
        ]

    return rows
