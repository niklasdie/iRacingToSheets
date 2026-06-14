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
from sheets import SheetWriter, df_to_values


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="iRacing .ibt telemetry → Google Sheets.")
    p.add_argument("ibt_file", nargs="?", help="Path to a .ibt file (default: newest found).")
    p.add_argument("--list", action="store_true", help="List .ibt files that can be found, then exit.")
    p.add_argument("--dry-run", action="store_true", help="Parse and analyse but do not upload.")
    return p.parse_args()


def candidate_dirs(cfg) -> list:
    """Telemetry folders to search, most-specific first, de-duplicated.

    Covers the standard location and the common Windows case where Documents is
    redirected into OneDrive.
    """
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
    """All .ibt files across candidate dirs, newest first."""
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
    """Fail early with clear guidance if the upload can't possibly work."""
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


def _print_tables(title, summary, field_df, laps_df, trace_df) -> None:
    print(f"\n=== {title} ===")
    print("\n[Summary]")
    for row in summary:
        print(f"  {row[0]:<26} {row[1]}")
    for name, df in (("Field Results", field_df), ("My Laps", laps_df),
                     ("Best Lap Telemetry", trace_df)):
        print(f"\n[{name}] ({len(df)} rows)")
        if not df.empty:
            print(df.head(12).to_string(index=False))


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

    path = resolve_ibt(cfg, args.ibt_file)
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

    if args.dry_run:
        _print_tables(title, summary, field_df, laps_df, trace_df)
        print("\n(dry run — nothing uploaded)")
        return

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
