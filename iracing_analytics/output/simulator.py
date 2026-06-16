"""Builds an interactive 'Simulator' tab as live Google Sheets formulas.

The `.ibt` is parsed once; the measured values (pace, degradation, fuel burn,
tank) and the strategy parameters (race length, pit loss, traffic, safety cars,
…) are written as editable cells, and every result is a formula referencing
them. The user then adjusts inputs in the sheet and everything recalculates —
no re-running the script, no re-parsing the file.

Layout is fixed so the formulas can reference cells by address:
  B4..B13   strategy inputs        B15..B18  measured (editable)
  B21..B28  key results            B29,D29   fuel/pace trade-off (editable)
  A32:J36   strategy comparison    A40:D43   safety-car sensitivity
  A47:C49   traffic sensitivity
"""
SC_PACE_FACTOR = 1.6
# Strategy-comparison sweep: how far the fuel target is allowed to move off the
# measured burn, and the lap-time it costs/gains at that extreme. Defaults the
# user can edit in the sheet (B29 / D29). Saving 0.5 L/lap ≈ 0.8 s/lap slower.
FUEL_RANGE_DEFAULT_L = 0.4
PACE_RANGE_DEFAULT_S = 0.8
# Safety reserve: fuel that must still be in the tank when you reach the pit
# (limits stint length), plus an extra lap carried for the end of a timed race —
# the last lap can be started after the clock hits 0 (the leader took the white
# with ~1 s left), so you must be able to finish one more lap than the time math.
END_BUFFER_DEFAULT_LAPS = 1
INPUT_RANGES = ["B4:B13", "B15:B18", "B29", "D29"]   # highlighted as "edit me" cells


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
    rows.append(["Pit reserve (L, min in tank at pit)", d["margin"]])      # B7
    rows.append(["Traffic (s/lap)", d["traffic"]])                        # B8
    rows.append(["Safety cars (expected)", d["safety_cars"]])             # B9
    rows.append(["SC minutes each", d["sc_minutes"]])                      # B10
    rows.append(["SC pit discount (0-1)", d["discount"]])                  # B11
    rows.append(["Drivers", d["drivers"]])                                 # B12
    rows.append(["End-of-race buffer (laps)", END_BUFFER_DEFAULT_LAPS])    # B13
    rows.append(["MEASURED (from telemetry — editable)", ""])
    rows.append(["Fresh-tyre pace (s/lap)", meas["p0"]])                   # B15
    rows.append(["Degradation (s/lap)", meas["deg"]])                      # B16
    rows.append(["Fuel burn (L/lap)", meas["burn"]])                       # B17
    rows.append(["Usable tank (L)", meas["tank"]])                         # B18
    rows.append(["", ""])
    rows.append(["KEY RESULTS (auto)", ""])
    rows.append(["Green pace (s/lap)", "=B15+B8"])                                          # B21
    rows.append(["Stint length — fuel (laps)", "=MAX(1,FLOOR((B18-B7)/B17))"])              # B22
    rows.append(["Avg lap @ full stint (s)", "=B21+B16*(B22-1)/2"])                         # B23
    rows.append(["Race target laps", "=IF(B5>0,B5,ROUND((B4*3600-MAX(0,CEILING((B4*3600/B23)/B22)-1)*B6)/B23))"])  # B24
    # Stops & fuel cover the laps you must carry fuel for: a timed race can run one
    # extra lap (B13) past the time math, so add it; a lap race ends on an exact
    # count. Reserve B7 (L) is the fuel still in the tank when you reach the pit.
    rows.append(["Minimum pit stops", "=MAX(0,CEILING((B24+IF(B5>0,0,B13))/B22)-1)"])       # B25
    rows.append(["Fuel to finish (L)", "=ROUND((B24+IF(B5>0,0,B13))*B17+B7,1)"])            # B26
    rows.append(["Race seconds (effective)", "=IF(B5>0,B24*B23,B4*3600)"])                  # B27
    rows.append(["Race time", '=TEXT(B27/86400,"[h]:mm:ss")'])                              # B28
    rows.append(["Fuel range ±(L/lap)", FUEL_RANGE_DEFAULT_L,
                 "Pace range ±(s/lap)", PACE_RANGE_DEFAULT_S])                              # B29 / D29 (editable)
    rows.append(["STRATEGY COMPARISON", "fuel-save vs lap-time trade-off around your measured burn (Δ0 = telemetry)"])
    rows.append(["Fuel Δ (L/lap)", "Target fuel (L/lap)", "Lap time (s/lap)", "Stint laps",
                 "Avg lap (s)", "Pit stops", "Total laps", "Race time", "Best", "(calc s)"])
    for r in range(32, 37):
        # Sweep the fuel target ±B29 around the measured burn (B17) in even steps.
        # factor: -1, -0.5, 0, +0.5, +1 — Δ0 is the measured baseline.
        factor = (r - 34) / 2
        rows.append([
            f"=ROUND({factor}*$B$29,2)",                                  # A: fuel Δ vs measured (L/lap)
            f"=ROUND($B$17+A{r},3)",                                      # B: target fuel (centred on B17)
            # C: less fuel ⇒ off the limit ⇒ slower; ±B29 L maps to ∓D29 s.
            f"=ROUND($B$21-({factor})*$D$29,3)",                          # C: lap time (s/lap)
            f"=MAX(1,FLOOR(($B$18-$B$7)/B{r}))",                          # D: stint laps (pit with ≥B7 L left)
            f"=ROUND(C{r}+$B$16*(D{r}-1)/2,2)",                           # E: avg lap incl. degradation
            # F: pit stops — timed race fuels for one extra lap (B13) past the time math.
            f"=IF($B$5>0,MAX(0,CEILING($B$5/D{r})-1),MAX(0,CEILING(($B$27/E{r}+$B$13)/D{r})-1))",  # F: pit stops
            f"=IF($B$5>0,$B$5,ROUND(($B$27-F{r}*$B$6)/E{r}))",           # G: total laps
            f'=TEXT(J{r}/86400,"[h]:mm:ss")',                            # H: race time
            f'=IF($B$5>0,IF(J{r}=MIN($J$32:$J$36),"◀ best",""),IF(G{r}=MAX($G$32:$G$36),"◀ best",""))',  # I: best
            # J: race seconds — lap race: laps×avg + pit time; timed: fixed race seconds.
            f"=IF($B$5>0,$B$5*E{r}+F{r}*$B$6,$B$27)",                    # J: race seconds (calc)
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
