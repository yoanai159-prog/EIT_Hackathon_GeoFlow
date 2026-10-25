# Ticha reservoir: real data (not simulated)

Source: Ministry of Environment and Water (MOEW), Bulgaria.

| File | What it is | Rows |
| --- | --- | --- |
| `ticha_monthly.csv` | Monthly water-use schedules ("Графици") for reservoir Ticha, 2014-01 to 2026-10, typed in from the PDFs | 143 months (some months have no file) |
| `ticha_daily.csv` | Daily bulletin rows for Ticha, 2026-08-10 to 2026-10-23 (working days) | 49 days |

Units: volumes in mln m3 (`_mm3`), flows in m3/s (`_m3s`), shares in % (`_pct`). Total capacity 311.8 mln m3, dead volume 40.0 mln m3.
`fill_pct` = `avail_mm3` / 311.8 x 100. `energy_mm3` is the water planned for the hydropower plants (only when the
reservoir is above about 260 mln m3); in those months the minimum-flow share is not listed separately, so `min_flow_mm3`
is 0 there. The schedules are a PLAN, not measurements. The monthly `avail_mm3` is the volume on the last working day before the month
starts (for example the September 2026 value equals the bulletin of 26 August).

Known problems in the source (kept as printed, flagged here):
- 2018-04: printed available volume 319.800, but the usable volume 271.800 implies 311.800 (likely a typo).
- 2015-04: available volume 313.800 is above the total capacity.
- 2018-08: printed total 8.248, the components add to 8.285.
- 2022-10: irrigation printed as 1,1585; the total implies 1.159.
- Possible copied values: 2015-07 and 2016-07; 2016-02 and 2016-08; 2017-04 and 2017-06.
- 2018-10: the page header prints "September" (typo in the source).
- 2025-12: the file holds the November schedule, so December 2025 is left out.
- Missing months (no schedule file available): 2016-12, 2020-06, 2021-02, 2023-09, 2024-05, 2024-10, 2024-11, 2025-01, 2025-02.
- 2020-01 and 2020-02: the text asks the water utilities of Shumen and Targovishte to activate alternative sources;
  2024-12: demands were reduced for a very dry year. These are real-world "warning" events for testing the traffic light.
