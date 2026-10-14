# StormSense Latest

The newest StormSense forecasts and sensor observations, chart pages and CSVs
in MLLW and NAVD88, served on GitHub Pages at fixed addresses that are
overwritten every 6 hours (nothing is archived):

    https://derekloftis.github.io/StormSense-latest/                         index
    https://derekloftis.github.io/StormSense-latest/fore56/SWPT_fore56_NAVD.html
    https://derekloftis.github.io/StormSense-latest/7day/SWPT_7day_MLLW.csv
    https://derekloftis.github.io/StormSense-latest/30day/SWPT_30day_NAVD.html

| Folder  | Product                    | Placeholder source for now     |
|---------|----------------------------|--------------------------------|
| fore56  | forecast (to become 56 h)  | Tidewatch 36 h forecast (f36)  |
| 7day    | recent observations        | Tidewatch 3-day hindcast (3d)  |
| 30day   | 30-day observations        | Tidewatch 30-day hindcast (30d)|

Charts are restyled by `styler/` with the StormSense logo and disclaimer.
MLLW charts carry the tidal datum lines (HAT+n to LAT, NAVD88) and m30; NAVD88
charts carry the MLLW line, m30 and the NWS flood categories (Action, Minor,
Moderate, Major) in NWPS's colors. Clicking a line's label hides or shows it.

Flood categories come from the National Water Prediction Service gauge API
(`make_thresholds.py`, stations mapped to NWS gauges in `stations_nws.csv`),
refreshed each run, with `thresholds.json` as the fallback. Gauges read in MLLW
are moved to NAVD88 with Tidewatch's own MLLW-NAVD88 offset for the station.

`.github/workflows/publish.yml` runs `publish.py` at 00:20, 06:20, 12:20 and
18:20 UTC (GitHub may start scheduled runs late) and on demand, then deploys.

Disclaimer: StormSense(TM) Predictive Plots are computer-generated operational
storm tide forecasts; the user assumes any and all risk.
