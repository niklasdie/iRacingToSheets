# iRacing → Google Sheets

A run-once Python script that analyses one iRacing session from a local **`.ibt`
telemetry file** and writes it to a Google Sheet for race prep.

It **auto-detects the session type** (endurance/race vs qualifying) and produces
the matching analytics, in up to six tabs:

- **Summary** — detected session type, track/car info, your result, pit-stop
  count, and clean-lap pace stats (best / average / median / consistency / fuel
  per lap).
- **Field Results** — every driver from the session: best & last lap, laps,
  incidents, iRating (from the file's SessionInfo).
- **My Laps** — your lap-by-lap times with a numeric `Seconds` column (chart it),
  the **stint** each lap belongs to, a lap **type** (out / green / in / pit),
  fuel used, max speed, and `Δ Best`.
- **Stints** *(race/endurance)* — one row per stint: laps, duration, best /
  average / median, **consistency** (std), **degradation** (s/lap trend), fuel
  used, fuel per lap, **refuel** amount, and the pit stop that ended it
  (duration + fuel added, flagged as a **possible driver change** on long team
  stops).
- **Qualifying** *(qualifying)* — flying-lap breakdown with gaps to your best,
  plus starting fuel.
- **Strategy** *(race/endurance)* — fuel-to-finish and pit-window projection:
  fuel burn (L/lap), laps per tank, fuel needed to finish, minimum pit stops,
  and for each stop a target lap, a pit **window** (earliest–latest lap), and the
  fuel to add. Race length is read from the file when it's a real race, or set it
  yourself with `--race-laps` / `--race-minutes` to plan an upcoming race from a
  practice run.
- **Best Lap Telemetry** — a downsampled trace of your fastest clean lap
  (Speed / Throttle / Brake / Gear / Steering vs lap distance) — chart it to see
  exactly where you're gaining or losing time.

### How stints and session type are detected

- **Stints** are split at detected **pit stops** (stationary in the pit box via
  the `PlayerCarInPitStall` channel, or pit road + near-zero speed as a
  fallback). Each stop records its **duration** and **fuel delta**, so refuels,
  splash-and-go, and long service/driver-change stops are distinguished. Out-laps
  and in-laps are excluded from pace stats; degradation is the lap-time trend
  across a stint's green laps.
- **Session type** uses the file's `SessionType` label first, then heuristics
  (lap count, pit stops, refuelling) so a qualifying *simulation* run inside a
  practice session is still recognised as qualifying-style.

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

Works on **Windows and macOS**.

## Quick start (easiest)

1. **Capture telemetry:** in iRacing, press **Alt+T** in-car to log telemetry.
   Drive. iRacing writes a `.ibt` to `Documents/iRacing/telemetry/`.
2. **Set up Google Sheets once** (section 3 below) and copy `.env.example`
   to `.env`.
3. **Run it:**
   - **Windows:** double-click **`run.bat`** (first run installs everything).
   - **macOS:** double-click **`run.command`**, or `./run.command` in a terminal.

With no arguments it finds your **newest** `.ibt` automatically (including
Documents folders redirected into OneDrive on Windows). That's it.

## 1. Capture telemetry in the sim

In iRacing, enable telemetry logging (press **Alt+T** in-car to toggle disk
logging, or set it always-on). Drive your session; iRacing writes a `.ibt` to
`Documents/iRacing/telemetry/`. On Windows the script finds it for you; on
macOS, copy the file over (or set `IRACING_TELEMETRY_DIR`).

## 2. Install

The launchers (`run.bat` / `run.command`) do this automatically. To do it by
hand:

```bash
python3 -m venv .venv            # "python" on Windows
source .venv/bin/activate        # .venv\Scripts\activate on Windows
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

Via the launcher (`run.bat` on Windows, `./run.command` on macOS) or directly
with `python main.py`. Any arguments after the launcher are passed through,
e.g. `run.bat --list`.

```bash
python main.py                       # newest .ibt found automatically
python main.py path/to/session.ibt   # a specific telemetry file
python main.py --list                # show every .ibt it can find, then exit
python main.py --dry-run             # parse + analyse, print to console, no upload
python main.py --race-laps 50        # project pit strategy for a 50-lap race
python main.py --race-minutes 120    # ...or a 2-hour timed race
```

Use `--dry-run` to check the analysis without needing Google set up yet. Strategy
defaults can also live in `.env` (`RACE_LAPS`, `RACE_MINUTES`,
`FUEL_MARGIN_LAPS`, `PIT_LOSS_SECONDS`); CLI flags override them.

## Notes

- `.env` and `service_account.json` hold secrets and are git-ignored — never
  commit them.
- "My Laps", pace stats, and the telemetry trace come from telemetry, so they
  cover **your** car only. "Field Results" covers the whole field from the
  file's SessionInfo.
- "Clean" laps exclude in/out (pit) laps. Lap times are derived from the
  session-time channel at each start/finish crossing.
