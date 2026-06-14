<div align="center">

# 🏎️ iRacing Telemetry Analytics

### An advanced race & endurance analytics tool for iRacing — from a single telemetry file straight to a Google Sheet

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS-lightgrey.svg)](#)
[![Data source](https://img.shields.io/badge/Data-iRacing%20.ibt%20telemetry-E1251B.svg)](#-why-ibt-telemetry-files)

</div>

---

Drop in one iRacing **`.ibt` telemetry file** and get a rich, shareable **Google Sheet** built for serious race prep: stint-by-stint breakdowns, pace & tyre **degradation**, lap **consistency**, **fuel burn**, and a complete **fuel-to-finish & pit-window strategy**. It even **auto-detects** whether the session is a race, an endurance stint, or qualifying, and tailors the analytics to match.

> **Capture telemetry on your sim rig → run one command → open the sheet.**
> No iRacing web API, no OAuth, no account hassle — just the data the sim already writes to disk.

---

## ✨ Highlights

- 🧮 **Advanced analytics, not just lap times** — consistency (std dev), degradation trend per stint, fuel-per-lap, optimal pace windows.
- 🛞 **Proper stint detection** — splits pit-to-pit (one tank), and correctly separates stints across **refuels** and **driver changes**.
- ⛽ **Fuel-to-finish & pit strategy** — laps per tank, fuel needed, minimum stops, and a **pit window** (earliest–latest lap) + fill for every stop.
- 🔮 **Full-race simulator** — no time to run a 6-hour race? Extrapolate one from a short practice stint: set the race length and it compares strategies and recommends stops, target lap times, and fuel.
- 🚦 **Traffic & safety-car sensitivity** — model a per-lap traffic penalty and see how expected safety cars shift your laps, optimal stops, and the time you save by pitting under yellow.
- 🔎 **Auto session detection** — race / endurance vs qualifying, with the right analytics for each.
- 📈 **Best-lap telemetry trace** — Speed / Throttle / Brake / Gear / Steering vs lap distance, ready to chart.
- 🖱️ **One-click** on Windows & macOS — double-click a launcher; it finds your newest telemetry file automatically.
- 🔓 **No web API needed** — works entirely from local `.ibt` files (see [why](#-why-ibt-telemetry-files)).

---

## 📊 What you get

Each run writes a Google Sheet with the tabs relevant to the session:

| Tab | When | What's in it |
|---|---|---|
| **Summary** | always | Detected session type, track/car, your result, pit-stop count, clean-lap pace stats, fuel/lap |
| **Field Results** | always | Every driver: best & last lap, laps, incidents, iRating |
| **My Laps** | always | Lap-by-lap times, the **stint** per lap, lap **type** (out/green/in/pit), fuel used, max speed, `Δ Best` |
| **Stints** | race / endurance | Per stint: laps, duration, best/avg/median, **consistency**, **degradation** (s/lap), fuel used & per lap, **refuel** amount, pit-stop summary (+ *possible driver change* flag) |
| **Strategy** | race / endurance | **Fuel to finish**, **minimum pit stops**, and per stop a target lap + **pit window** + fuel to add |
| **Race Sim** | race / endurance | **Full-race simulation** for an adjustable race length — compares pit-stop strategies and recommends one, with a stint-by-stint plan, target lap times, fuel and timing |
| **Qualifying** | qualifying | Flying-lap breakdown with gaps to your best, plus starting fuel |
| **Best Lap Telemetry** | always | Downsampled trace of your fastest clean lap — chart it to find where you gain/lose time |

---

## 🚀 Quick start

```text
1. In iRacing, press Alt+T in the car to log telemetry, then drive.
2. Set up Google Sheets once (see Setup) and copy .env.example → .env
3. Run:
     Windows → double-click  run.bat
     macOS   → double-click  run.command   (or ./run.command)
```

With no arguments it finds your **newest** `.ibt` automatically (including
Documents folders redirected into OneDrive on Windows). First run installs
everything into a local virtual environment. That's it.

> 💡 Not set up Google yet? Run `python main.py --dry-run` to print the full
> analysis to your console without uploading anything.

---

## 🔧 Setup

### 1. Capture telemetry

In iRacing, press **Alt+T** in-car to toggle disk telemetry (or set it
always-on). The sim writes a `.ibt` to `Documents/iRacing/telemetry/`. On Windows
the tool finds it for you; on macOS, copy the file over or set
`IRACING_TELEMETRY_DIR`.

### 2. Install

The launchers (`run.bat` / `run.command`) do this for you. To do it by hand:

```bash
python3 -m venv .venv            # "python" on Windows
source .venv/bin/activate        # .venv\Scripts\activate on Windows
pip install -r requirements.txt
```

<details>
<summary><b>3. Set up Google Sheets (service account) — click to expand</b></summary>

1. Go to <https://console.cloud.google.com/> and create a project.
2. **APIs & Services → Library**: enable both **Google Sheets API** and **Google Drive API**.
3. **APIs & Services → Credentials → Create credentials → Service account**, then create it.
4. Open the service account → **Keys → Add key → Create new key → JSON**. Save it as `service_account.json` in this folder.
5. Copy the service account's email (`name@project.iam.gserviceaccount.com`).

Then pick how the sheet is delivered (in `.env`):

- **A (default):** set `GOOGLE_SHARE_EMAIL` to your Gmail and leave `GOOGLE_SHEET_ID` blank — a new spreadsheet is created each run and shared with you.
- **B:** create a blank sheet, share it (Editor) with the service-account email, and put its id in `GOOGLE_SHEET_ID`.

</details>

### 4. Configure

```bash
cp .env.example .env
```

Fill in your Google credentials path and sheet option. Everything else has
sensible defaults.

---

## ⚙️ Usage & options

Run via a launcher (`run.bat` / `./run.command`) or directly with `python main.py`.
Arguments after the launcher are passed through (e.g. `run.bat --dry-run`).

```bash
python main.py                       # newest .ibt found automatically
python main.py path/to/session.ibt   # a specific telemetry file
python main.py --list                # show every .ibt it can find, then exit
python main.py --dry-run             # parse + analyse, print to console, no upload
python main.py --race-laps 50        # strategy + simulation for a 50-lap race
python main.py --race-hours 6        # simulate a 6-hour endurance race
python main.py --race-hours 6 --deg-per-lap 0.08 --drivers 3   # tuned sim
```

| Flag | Purpose |
|---|---|
| `--list` | List the `.ibt` files the tool can find |
| `--dry-run` | Analyse and print to console; don't upload |
| `--race-laps N` | Race length in laps (strategy + simulation) |
| `--race-minutes M` / `--race-hours H` | Race length for a timed race |
| `--margin-laps X` | Fuel safety reserve, in laps (default `0.3`) |
| `--pit-loss S` | Seconds lost per pit stop (default `30`) |
| `--deg-per-lap X` | Override tyre degradation in the sim (s/lap) |
| `--pace-offset S` | Add to fresh-lap pace in the sim (+ = saving) |
| `--max-stint-minutes M` | Cap stint length by time (tyre/driver limit) |
| `--drivers N` | Driver count (endurance) → stints per driver |
| `--traffic-loss S` | Seconds added per green lap from traffic |
| `--safety-cars N` | Expected safety-car periods (sensitivity range) |
| `--sc-minutes M` | Minutes per safety-car period (default `5`) |
| `--sc-pit-discount F` | Fraction of pit loss still paid under SC (default `0.4`) |

Defaults can also live in `.env` (`RACE_LAPS`, `RACE_MINUTES`, `RACE_HOURS`,
`FUEL_MARGIN_LAPS`, `PIT_LOSS_SECONDS`, `SIM_DEG_PER_LAP`, `SIM_PACE_OFFSET`,
`MAX_STINT_MINUTES`, `DRIVERS`, `TRAFFIC_LOSS`, `SAFETY_CARS`, `SC_MINUTES`,
`SC_PIT_DISCOUNT`); CLI flags override them.

---

## 🧠 How it works

- **Stints** are split at detected **pit stops** — stationary in the pit box
  (`PlayerCarInPitStall`), or pit road + near-zero speed as a fallback. Each stop
  records its **duration** and **fuel delta**, so refuels, splash-and-go, and long
  service/driver-change stops are told apart. Out-/in-laps are excluded from pace
  stats; **degradation** is the lap-time trend across a stint's green laps.
- **Session type** uses the file's `SessionType` first, then heuristics (lap
  count, pit stops, refuelling) — so a qualifying *simulation* run inside a
  practice session is still recognised as qualifying-style.
- **Strategy** combines measured fuel burn, green-lap pace, tank capacity
  (`DriverCarFuelMaxLtr × DriverCarMaxFuelPct`) and race length (from the file or
  your `--race-*` override) into a fuel-to-finish and pit-window plan.
- **Race Sim** extrapolates a full race from your short run: each stint runs at
  `fresh pace + degradation × lap`, capped by fuel (and an optional max stint
  time); it simulates several pit-stop counts and recommends the one that
  **completes the most laps** (timed race) or **finishes soonest** (lap race) —
  balancing tyre degradation against pit-stop time loss.
- **Traffic** is a per-lap penalty added to green pace, so it feeds the whole
  optimisation. **Safety cars** are shown as a sensitivity range: each period
  neutralises the race at ~1.6× lap time (costing laps), but pitting under yellow
  only pays a fraction of the normal pit loss — the table shows the net effect on
  total laps / finish time and the pit time saved. It's a planning baseline that
  still assumes otherwise-steady running (no weather, no incidents).

## 🏁 Why `.ibt` telemetry files?

iRacing has two separate data sources:

- The web **`/data` API** needs **OAuth2** (legacy email/password auth was retired
  2025-12-09) and iRacing has **paused issuing new OAuth client IDs** — so it's
  currently unusable for new third-party scripts.
- The local **iRacing SDK** writes a **`.ibt`** telemetry file per session. It's a
  different API, **not affected by the OAuth pause**, and carries richer data
  (real telemetry traces).

This tool uses `.ibt` files. iRacing runs on Windows, so capture there, then
analyse anywhere — parsing is plain file I/O and runs on macOS too.

> An OAuth2 web-API implementation is also included (`iracing_client.py` +
> `iracing_oauth.py`) for the day registration reopens, but it is not wired into
> `main.py`.

---

## 📝 Notes

- `.env` and `service_account.json` hold secrets and are git-ignored — never commit them.
- "My Laps", pace stats, and the telemetry trace cover **your** car only (that's what telemetry logs). "Field Results" covers the whole field from the file's SessionInfo.
- Strategy assumes steady pace/burn and even stints (no fuel-saving or safety-car modelling); timed-race lap counts are an estimate — tune `--pit-loss` to your track.

---

## 📜 License

Released under the **[MIT License](LICENSE)** — **free for anyone to use**, copy,
modify, and distribute, for any purpose, commercial or personal, at no cost.

## ⚠️ Disclaimer

This project is an independent, community tool and is **not affiliated with,
endorsed by, or sponsored by iRacing.com Motorsport Simulations, LLC**. "iRacing"
and related marks belong to their respective owners.

The software is provided **"as is", without warranty of any kind**. You use it at
your own risk, and **the authors accept no liability** for any damages, data loss,
incorrect strategy calls, or other consequences arising from its use. Always
sanity-check fuel and strategy numbers before relying on them.
