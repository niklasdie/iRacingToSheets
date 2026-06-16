"""Builds an interactive 'Simulator' tab as live Google Sheets formulas.

The `.ibt` is parsed once; the measured values (pace, degradation, fuel burn,
tank) and the strategy parameters (race length, pit loss, traffic, safety cars,
…) are written as editable cells, and every result is a formula referencing
them. The user then adjusts inputs in the sheet and everything recalculates —
no re-running the script, no re-parsing the file.

Layout is fixed so the formulas can reference cells by address:
  B4..B12   strategy inputs        B15..B18  measured (editable)
  B21..B28  key results            A32:J36   strategy comparison
  A40:D43   safety-car sensitivity A47:C49   traffic sensitivity
"""
SC_PACE_FACTOR = 1.6
INPUT_RANGES = ["B4:B12", "B15:B18"]   # highlighted as "edit me" cells


def measured(session, lap_df, stats):
    """Pull the values the sim extrapolates from. Returns None if too sparse."""
    from ..analysis import race_sim, strategy
    p0 = race_sim.base_pace(lap_df, stats)
    burn, _ = strategy.fuel_basis(lap_df, stats)
    tank, _, _ = strategy.usable_tank(session)
    if not p0 or not burn or not tank:
        return None
    return {
        "p0": round(p0, 3),
        "deg": round(max(0.0, race_sim.deg_estimate(lap_df)), 4),
        "burn": round(burn, 3),
        "tank": round(tank, 1),
    }


def build(meas: dict | None, d: dict):
    """Return (rows, input_ranges) for the Simulator tab.

    `d` holds the input defaults (from CLI/.env): hours, race_laps, pit_loss,
    margin, traffic, safety_cars, sc_minutes, discount, drivers.
    """
    if not meas:
        return [["Simulator", "Not enough clean-lap fuel/pace data in this file to simulate."]], []

    rows = []
    rows.append(["⚙️ SIMULATOR", "Edit the highlighted cells in column B — every result below recalculates live."])
    rows.append(["", ""])
    rows.append(["INPUTS", ""])
    rows.append(["Race length — hours", d["hours"]])                       # B4
    rows.append(["Race length — laps (0 = use hours)", d["race_laps"]])    # B5
    rows.append(["Pit loss per stop (s)", d["pit_loss"]])                  # B6
    rows.append(["Fuel margin (laps)", d["margin"]])                       # B7
    rows.append(["Traffic (s/lap)", d["traffic"]])                        # B8
    rows.append(["Safety cars (expected)", d["safety_cars"]])             # B9
    rows.append(["SC minutes each", d["sc_minutes"]])                      # B10
    rows.append(["SC pit discount (0-1)", d["discount"]])                  # B11
    rows.append(["Drivers", d["drivers"]])                                 # B12
    rows.append(["", ""])
    rows.append(["MEASURED (from telemetry — editable)", ""])
    rows.append(["Fresh-tyre pace (s/lap)", meas["p0"]])                   # B15
    rows.append(["Degradation (s/lap)", meas["deg"]])                      # B16
    rows.append(["Fuel burn (L/lap)", meas["burn"]])                       # B17
    rows.append(["Usable tank (L)", meas["tank"]])                         # B18
    rows.append(["", ""])
    rows.append(["KEY RESULTS (auto)", ""])
    rows.append(["Green pace (s/lap)", "=B15+B8"])                                          # B21
    rows.append(["Stint length — fuel (laps)", "=MAX(1,FLOOR((B18-B7*B17)/B17))"])          # B22
    rows.append(["Avg lap @ full stint (s)", "=B21+B16*(B22-1)/2"])                         # B23
    rows.append(["Race target laps", "=IF(B5>0,B5,ROUND((B4*3600-MAX(0,CEILING((B4*3600/B23)/B22)-1)*B6)/B23))"])  # B24
    rows.append(["Minimum pit stops", "=MAX(0,CEILING(B24/B22)-1)"])                        # B25
    rows.append(["Fuel to finish (L)", "=ROUND(B24*B17+B7*B17,1)"])                         # B26
    rows.append(["Race seconds (effective)", "=IF(B5>0,B24*B23,B4*3600)"])                  # B27
    rows.append(["Race time", '=TEXT(B27/86400,"[h]:mm:ss")'])                              # B28
    rows.append(["", ""])
    rows.append(["STRATEGY COMPARISON", "timed: most laps wins · lap race: least time wins"])
    rows.append(["Pit stops", "Stint laps", "Avg lap (s)", "Total laps", "Fuel (L)", "Target fuel (L/lap)", "Finish", "Best", "(calc L)", "(calc s)"])
    for r in range(32, 37):
        o = r - 32
        rows.append([
            f"=$B$25+{o}",                                         # A: pit stops
            f"=ROUND(I{r})",                                       # B: stint laps (display)
            f"=ROUND($B$21+$B$16*(I{r}-1)/2,2)",                   # C: avg lap
            f"=IF($B$5>0,$B$5,ROUND((A{r}+1)*I{r}))",             # D: total laps
            f"=ROUND(D{r}*$B$17)",                                 # E: fuel needed (total L)
            # F: fuel/lap to target so each stint (I laps + B7-lap margin) finishes on
            #    one tank — the fuel-save target needed to reach this row's lap count.
            f"=ROUND($B$18/(I{r}+$B$7),3)",                        # F: target fuel (L/lap)
            f'=TEXT(J{r}/86400,"[h]:mm:ss")',                      # G: finish (lap race)
            f'=IF($B$5>0,IF(J{r}=MIN($J$32:$J$36),"◀ best",""),IF(D{r}=MAX($D$32:$D$36),"◀ best",""))',
            # I: continuous stint length (laps), capped by fuel; quadratic solves the
            #    time available per stint against fresh pace + degradation.
            (f"=IF($B$5>0,$B$5/(A{r}+1),MIN($B$22,IF($B$16=0,"
             f"(($B$27-A{r}*$B$6)/(A{r}+1))/$B$21,"
             f"(SQRT(($B$21-$B$16/2)^2+2*$B$16*(($B$27-A{r}*$B$6)/(A{r}+1)))-($B$21-$B$16/2))/$B$16)))"),
            # J: finish time in seconds (lap race) / race seconds (timed)
            f"=IF($B$5>0,$B$5*$B$21+$B$16/2*$B$5*($B$5/(A{r}+1)-1)+A{r}*$B$6,$B$27)",
        ])
    rows.append(["", ""])
    rows.append(["SAFETY-CAR SENSITIVITY", f"each SC ~1.6x lap; pit under yellow pays the discount only"])
    rows.append(["Safety cars", "Total laps", "Pit saved (s)", "vs 0 SC"])
    for r in range(40, 44):
        k = r - 40
        rows.append([
            k,
            (f"=ROUND(($B$27-{k}*$B$10*60+MIN({k},$B$25)*(1-$B$11)*$B$6)/$B$23)"
             f"+INT({k}*$B$10*60/($B$15*{SC_PACE_FACTOR}))"),
            f"=ROUND(MIN({k},$B$25)*(1-$B$11)*$B$6)",
            f"=B{r}-$B$40",
        ])
    rows.append(["", ""])
    rows.append(["TRAFFIC SENSITIVITY", "total laps at higher traffic levels"])
    rows.append(["Traffic (s/lap)", "Total laps", "vs base"])
    for i, r in enumerate(range(47, 50)):
        delta = [0.0, 0.5, 1.0][i]
        rows.append([
            f"=$B$8+{delta}",
            f"=ROUND(($B$27-$B$25*$B$6)/(($B$15+$B$8+{delta})+$B$16*($B$22-1)/2))",
            f"=B{r}-$B$47",
        ])
    return rows, INPUT_RANGES
