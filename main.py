"""Analyse one iRacing `.ibt` telemetry file and upload it to Google Sheets.

Run once and exit:

    python main.py path/to/session.ibt   # a specific telemetry file
    python main.py                        # newest .ibt in IRACING_TELEMETRY_DIR

Telemetry comes from the local iRacing SDK (.ibt files), which is unaffected by
the web Data API's OAuth pause. Enable telemetry logging in the sim, copy the
.ibt off the Windows box, and point this at it.
"""
import argparse
import glob
import os

from config import load_config
from ibt_client import IBTSession
import ibt_analysis as A
from sheets import SheetWriter, df_to_values


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="iRacing .ibt telemetry → Google Sheets.")
    p.add_argument("ibt_file", nargs="?", help="Path to a .ibt file (default: newest in telemetry dir).")
    return p.parse_args()


def find_latest_ibt(directory: str) -> str:
    files = glob.glob(os.path.join(os.path.expanduser(directory), "*.ibt"))
    if not files:
        raise SystemExit(
            f"No .ibt files found in {directory}. Pass a file path explicitly, "
            "or set IRACING_TELEMETRY_DIR in .env."
        )
    return max(files, key=os.path.getmtime)


def main() -> None:
    args = parse_args()
    cfg = load_config()

    path = args.ibt_file or find_latest_ibt(cfg.telemetry_dir)
    if not os.path.exists(path):
        raise SystemExit(f"File not found: {path}")

    print(f"Parsing {path} ...")
    session = IBTSession(path)
    try:
        field_df = A.field_results_df(session.session_info)
        laps_df = A.my_laps_df(session)
        stats = A.lap_stats(laps_df)
        best_lap = A.best_clean_lap(laps_df)
        trace_df = A.best_lap_trace_df(session, best_lap)
        summary = A.summary_rows(session.session_info, stats, best_lap, laps_df)
        title = A.build_title(session.session_info)
    finally:
        session.close()

    print("Uploading to Google Sheets ...")
    writer = SheetWriter(cfg.google_creds_path)
    sh = writer.open_or_create(cfg.google_sheet_id, title, cfg.google_share_email)
    writer.write_tab(sh, "Summary", summary)
    if not field_df.empty:
        writer.write_tab(sh, "Field Results", df_to_values(field_df))
    if not laps_df.empty:
        writer.write_tab(sh, "My Laps", df_to_values(laps_df))
    if not trace_df.empty:
        writer.write_tab(sh, "Best Lap Telemetry", df_to_values(trace_df))
    writer.remove_default_sheet(sh)

    print(f"Done → {sh.url}")


if __name__ == "__main__":
    main()
