# iRacing → Google Sheets

A run-once Python script that analyses one iRacing session from a local **`.ibt`
telemetry file** and writes it to a Google Sheet for race prep.

It creates up to four tabs:

- **Summary** — track/car/session info, your result, and clean-lap pace stats
  (best / average / median / consistency).
- **Field Results** — every driver from the session: best & last lap, laps,
  incidents, iRating (from the file's SessionInfo).
- **My Laps** — your lap-by-lap times with a numeric `Seconds` column (chart it),
  max speed, and `Δ Best` (gap of each lap to your best clean lap).
- **Best Lap Telemetry** — a downsampled trace of your fastest clean lap
  (Speed / Throttle / Brake / Gear / Steering vs lap distance) — chart it to see
  exactly where you're gaining or losing time.

## Why `.ibt` files (and not the web API)

iRacing has two separate data sources:

- The web **`/data` API** — needs **OAuth2** (legacy email/password auth was
  retired 2025-12-09) and iRacing has **paused issuing new OAuth client IDs**, so
  it's currently unusable for new third-party scripts.
- The local **iRacing SDK** — writes a **`.ibt`** telemetry file per session to
  `Documents/iRacing/telemetry/`. This is a different API, **not affected by the
  OAuth pause**, and gives richer data (real telemetry traces).

This tool uses `.ibt` files. iRacing runs on Windows, so capture the file on the
sim box, then analyse it anywhere — parsing is plain file I/O and works on macOS.

> An OAuth2 web-API implementation is also included (`iracing_client.py` +
> `iracing_oauth.py`) for the day registration reopens, but it is not wired into
> `main.py`.

## 1. Capture telemetry in the sim

In iRacing, enable telemetry logging (press **Alt+T** in-car to toggle disk
logging, or set it always-on). Drive your session; iRacing writes a `.ibt` to
`Documents/iRacing/telemetry/`. Copy that file to wherever you run this script.

## 2. Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 3. Set up Google credentials (service account)

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

## 4. Configure

```bash
cp .env.example .env
```

Fill in the Google credentials path and your sheet option from step 3.
Optionally set `IRACING_TELEMETRY_DIR` if your `.ibt` files live somewhere other
than `~/Documents/iRacing/telemetry`.

## 5. Run

```bash
python main.py path/to/session.ibt   # a specific telemetry file
python main.py                       # newest .ibt in IRACING_TELEMETRY_DIR
```

## Notes

- `.env` and `service_account.json` hold secrets and are git-ignored — never
  commit them.
- "My Laps", pace stats, and the telemetry trace come from telemetry, so they
  cover **your** car only. "Field Results" covers the whole field from the
  file's SessionInfo.
- "Clean" laps exclude in/out (pit) laps. Lap times are derived from the
  session-time channel at each start/finish crossing.
