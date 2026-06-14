"""Analyse one iRacing `.ibt` telemetry file and upload it to Google Sheets.

Run once and exit. Cross-platform (Windows + macOS).

    python main.py                       # newest .ibt found automatically
    python main.py path/to/session.ibt   # a specific telemetry file
    python main.py --list                # list .ibt files it can find
    python main.py --dry-run             # parse + analyse, print, don't upload

On Windows you can just double-click run.bat (it sets everything up).
"""
import argparse
import glob
import os

from config import load_config
from ibt_client import IBTSession
import ibt_analysis as A
import stints
import strategy
from sheets import SheetWriter, df_to_values


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="iRacing .ibt telemetry → Google Sheets.")
    p.add_argument("ibt_file", nargs="?", help="Path to a .ibt file (default: newest found).")
    p.add_argument("--list", action="store_true", help="List .ibt files that can be found, then exit.")
    p.add_argument("--dry-run", action="store_true", help="Parse and analyse but do not upload.")
    p.add_argument("--race-laps", type=int, help="Project strategy for a race of this many laps.")
    p.add_argument("--race-minutes", type=float, help="Project strategy for a timed race (minutes).")
    p.add_argument("--margin-laps", type=float, help="Fuel safety reserve in laps (default 0.3).")
    p.add_argument("--pit-loss", type=float, help="Seconds lost per stop, for timed-race lap estimate (default 30).")
    return p.parse_args()


def candidate_dirs(cfg) -> list:
    raw = [
        cfg.telemetry_dir,
        "~/Documents/iRacing/telemetry",
        "~/OneDrive/Documents/iRacing/telemetry",
        os.path.join(os.environ.get("USERPROFILE", "~"), "Documents", "iRacing", "telemetry"),
    ]
    seen, dirs = set(), []
    for d in raw:
        full = os.path.abspath(os.path.expanduser(d))
        if full not in seen:
            seen.add(full)
            dirs.append(full)
    return dirs


def find_ibt_files(cfg) -> list:
    files = []
    for d in candidate_dirs(cfg):
        files.extend(glob.glob(os.path.join(d, "*.ibt")))
    return sorted(set(files), key=os.path.getmtime, reverse=True)


def resolve_ibt(cfg, explicit: str | None) -> str:
    if explicit:
        if not os.path.exists(explicit):
            raise SystemExit(f"File not found: {explicit}")
        return explicit
    files = find_ibt_files(cfg)
    if not files:
        raise SystemExit(
            "No .ibt files found. Checked:\n  "
            + "\n  ".join(candidate_dirs(cfg))
            + "\n\nEnable telemetry in the sim (Alt+T), or pass a file path, or set "
            "IRACING_TELEMETRY_DIR in .env."
        )
    return files[0]


def check_google_config(cfg) -> None:
    if not os.path.exists(cfg.google_creds_path):
        raise SystemExit(
            f"Google credentials not found at '{cfg.google_creds_path}'. "
            "See README step 3 (create a service account, save service_account.json), "
            "or run with --dry-run to skip uploading."
        )
    if not cfg.google_sheet_id and not cfg.google_share_email:
        raise SystemExit(
            "No Google Sheet target. Set GOOGLE_SHEET_ID (an existing sheet shared "
            "with the service account) or GOOGLE_SHARE_EMAIL (to create one and share "
            "it with you) in .env — or run with --dry-run."
        )


def build_tabs(session, opts) -> tuple:
    """Analyse the session into an ordered list of (tab_name, values) tabs."""
    lap_df = A.lap_table(session)
    stops = A.detect_stops(session)
    detected, reason = stints.classify_session(session, lap_df, stops)
    stats = A.lap_stats(lap_df)
    best_lap = A.best_clean_lap(lap_df)
    trace_df = A.best_lap_trace_df(session, best_lap)
    title = A.build_title(session.session_info)

    tabs = [
        ("Summary", A.summary_rows(session.session_info, stats, best_lap, lap_df, detected, len(stops))),
    ]
    field_df = A.field_results_df(session.session_info)
    if not field_df.empty:
        tabs.append(("Field Results", df_to_values(field_df)))
    if not lap_df.empty:
        tabs.append(("My Laps", df_to_values(A.laps_view(lap_df))))

    if "Qualifying" in detected:
        tabs.append(("Qualifying", stints.qualifying_summary(lap_df)))
    else:
        stint_df = stints.stint_table(lap_df, stops, session.session_info)
        if not stint_df.empty:
            tabs.append(("Stints", df_to_values(stint_df)))
        tabs.append(("Strategy", strategy.project(
            session, lap_df, stats, opts["race_laps"], opts["race_minutes"],
            opts["margin_laps"], opts["pit_loss_s"])))

    if not trace_df.empty:
        tabs.append(("Best Lap Telemetry", df_to_values(trace_df)))
    return title, detected, reason, tabs


def _print_tabs(title, detected, reason, tabs) -> None:
    print(f"\n=== {title} ===")
    print(f"Detected session type: {detected}  ({reason})")
    for name, values in tabs:
        print(f"\n[{name}] ({max(len(values) - 1, 0)} rows)")
        for row in values[:14]:
            print("  " + " | ".join("" if v is None else str(v) for v in row))


def main() -> None:
    args = parse_args()
    cfg = load_config()

    if args.list:
        files = find_ibt_files(cfg)
        if not files:
            print("No .ibt files found. Checked:\n  " + "\n  ".join(candidate_dirs(cfg)))
            return
        print(f"Found {len(files)} .ibt file(s) (newest first):")
        for f in files:
            print(f"  {f}")
        return

    if not args.dry_run:
        check_google_config(cfg)

    opts = {
        "race_laps": args.race_laps if args.race_laps is not None else cfg.race_laps,
        "race_minutes": args.race_minutes if args.race_minutes is not None else cfg.race_minutes,
        "margin_laps": args.margin_laps if args.margin_laps is not None else cfg.fuel_margin_laps,
        "pit_loss_s": args.pit_loss if args.pit_loss is not None else cfg.pit_loss_s,
    }

    path = resolve_ibt(cfg, args.ibt_file)
    print(f"Parsing {path} ...")
    session = IBTSession(path)
    try:
        title, detected, reason, tabs = build_tabs(session, opts)
    finally:
        session.close()

    if args.dry_run:
        _print_tabs(title, detected, reason, tabs)
        print("\n(dry run — nothing uploaded)")
        return

    print(f"Detected session type: {detected} ({reason})")
    print("Uploading to Google Sheets ...")
    writer = SheetWriter(cfg.google_creds_path)
    sh = writer.open_or_create(cfg.google_sheet_id, title, cfg.google_share_email)
    for name, values in tabs:
        writer.write_tab(sh, name, values)
    writer.remove_default_sheet(sh)

    print(f"Done → {sh.url}")


if __name__ == "__main__":
    main()
