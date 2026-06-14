# iRacing → Google Sheets

A run-once Python script that pulls one iRacing session (your latest race or a
specific subsession), analyses the results and your lap times, and writes them
to a Google Sheet for race prep.

It creates three tabs:

- **Summary** — session info plus your result and clean-lap pace stats
  (best / average / median / consistency).
- **Field Results** — every driver: best & average lap, laps, incidents,
  start/finish, iRating change.
- **My Laps** — your lap-by-lap times with a numeric `Seconds` column (chart it)
  and `Δ Best` (gap of each lap to your best clean lap).

Data comes from the official **iRacing Data API** — no sim or Windows required.

## 1. Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. Set up Google credentials (service account)

1. Go to <https://console.cloud.google.com/> and create a project.
2. **APIs & Services → Library**: enable both **Google Sheets API** and
   **Google Drive API**.
3. **APIs & Services → Credentials → Create credentials → Service account**.
   Give it any name and click through to create it.
4. Open the service account → **Keys → Add key → Create new key → JSON**.
   Save the downloaded file as `service_account.json` in this folder.
5. Copy the service account's email — it looks like
   `name@project.iam.gserviceaccount.com`.

You then have two ways to deliver the sheet (pick one in `.env`):

- **A (default):** set `GOOGLE_SHARE_EMAIL` to your Gmail and leave
  `GOOGLE_SHEET_ID` blank. The script creates a new spreadsheet each run and
  shares it with you.
- **B:** create one blank sheet in your Drive, share it (Editor) with the
  service account email, and put its id in `GOOGLE_SHEET_ID`.

## 3. Configure

```bash
cp .env.example .env
```

Fill in your iRacing email/password, your `IRACING_CUST_ID` (on your iRacing
profile page), the Google credentials path, and your sheet option from step 2.

## 4. Run

```bash
python main.py                    # your most recent race
python main.py --subsession 12345 # a specific subsession (id from a results URL)
python main.py --cust-id 654321   # analyse a different driver in that session
```

## Notes

- `.env` and `service_account.json` hold secrets and are git-ignored — never
  commit them.
- "My Laps" / pace stats need a customer id (`IRACING_CUST_ID` or `--cust-id`).
  Without one the script still writes Summary + Field Results.
- Times are read from the API in ten-thousandths of a second and converted to
  `M:SS.mmm`. "Clean" laps exclude pit/off-track/incident laps.
