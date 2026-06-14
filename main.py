"""Fetch one iRacing session, analyse it, and upload the result to Google Sheets.

Run once and exit:

    python main.py                      # your most recent race
    python main.py --subsession 12345   # a specific subsession id
    python main.py --cust-id 654321     # analyse a different driver
"""
import argparse

from config import load_config
from iracing_client import IRacingClient
import analysis
from sheets import SheetWriter, df_to_values


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="iRacing session → Google Sheets.")
    p.add_argument("--subsession", type=int, help="Subsession id (default: your latest race).")
    p.add_argument("--cust-id", type=int, help="Driver to analyse (default: IRACING_CUST_ID).")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    cfg = load_config()
    cust_id = args.cust_id or cfg.iracing_cust_id

    client = IRacingClient(cfg.iracing_email, cfg.iracing_password)

    # 1. Decide which session to pull.
    if args.subsession:
        subsession_id = args.subsession
    else:
        if not cust_id:
            raise SystemExit(
                "Latest-race mode needs a customer id. "
                "Set IRACING_CUST_ID in .env or pass --cust-id, "
                "or pass --subsession <id>."
            )
        subsession_id = client.latest_subsession_id(cust_id)
    print(f"Fetching subsession {subsession_id} ...")

    # 2. Fetch + analyse.
    result = client.session_result(subsession_id)
    race = analysis.pick_race_simsession(result)
    field_df = analysis.field_results_df(race)

    my_laps = None
    stats = {}
    if cust_id:
        laps = client.lap_data(subsession_id, cust_id, race.get("simsession_number", 0))
        my_laps = analysis.my_laps_df(laps, cust_id)
        stats = analysis.lap_stats(my_laps)
    else:
        print("No customer id set — skipping per-lap analysis (field results only).")

    summary = analysis.summary_rows(result, race, cust_id, stats)

    # 3. Upload.
    print("Uploading to Google Sheets ...")
    writer = SheetWriter(cfg.google_creds_path)
    sh = writer.open_or_create(
        cfg.google_sheet_id, analysis.build_title(result), cfg.google_share_email
    )
    writer.write_tab(sh, "Summary", summary)
    writer.write_tab(sh, "Field Results", df_to_values(field_df))
    if my_laps is not None and not my_laps.empty:
        writer.write_tab(sh, "My Laps", df_to_values(my_laps))
    writer.remove_default_sheet(sh)

    print(f"Done → {sh.url}")


if __name__ == "__main__":
    main()
