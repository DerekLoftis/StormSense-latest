# StormSense Latest

The newest StormSense forecasts and sensor observations, chart pages and CSVs
in MLLW and NAVD88, served on GitHub Pages at fixed addresses that are
overwritten every 6 hours (nothing is archived):

    https://derekloftis.github.io/StormSense-latest/                         index
    https://derekloftis.github.io/StormSense-latest/fore72/SWPT_fore72_NAVD.html
    https://derekloftis.github.io/StormSense-latest/7day/SWPT_7day_MLLW.csv
    https://derekloftis.github.io/StormSense-latest/30day/SWPT_30day_NAVD.html

| Folder  | Product                    | Source                                                   |
|---------|----------------------------|----------------------------------------------------------|
| fore72  | 72-hour forecast           | NWS P-ETSS (NOMADS), newest cycle; Tidewatch 36 h where P-ETSS has no point |
| 7day    | last 7 days                | gauge observations (Tidewatch 30d + 3d) with P-ETSS/CO-OPS tide |
| 30day   | last 30 days               | gauge observations (Tidewatch 30d) with P-ETSS/CO-OPS tide |

fore72 (`petss.py`, `products.py`): P-ETSS posts hourly storm tide (tide +
ensemble surge + observation bias) with 10% and 90% exceedance levels. Each
hourly series is interpolated to 6 minutes, smoothed with a 3-hour Hann
low-pass filter and added to the 6-minute harmonic tide, over 72 hours from the
start of Tidewatch's forecast window. P-ETSS is tied to each gauge's own record
by the median gap between observations and P-ETSS over the previous day (this
matters at P-ETSS's "est" sites, which use a different reference). The chart
shades the 10%-90% range as a cone of uncertainty in StormSense dark blue.

    fore72 CSV/JSON: date_time_z, astro_tide_ft, surge_ft, bias_ft, residual_ft, SSforecast_ft,
                SSforecast_p10_ft, SSforecast_p90_ft, surge_p10_ft, surge_p90_ft
    7day/30day CSV/JSON: date_time_z, water_level_ft, astro_tide_ft, residual_ft

residual = SSforecast - astro_tide (forecast) or water_level_ft - astro_tide
(hindcast). The hindcast tide is P-ETSS's (about 6 days back) and NOAA CO-OPS
predictions further back at NOAA stations; elsewhere older rows leave it blank.

Charts are restyled by `styler/` with the StormSense logo and disclaimer.
MLLW charts carry the tidal datum lines (HAT+n to LAT, NAVD88); NAVD88 charts
carry the MLLW line and the NWS flood categories (Action, Minor, Moderate,
Major) in NWPS's colors. Clicking a line's label hides or shows it.

Flood categories come from the National Water Prediction Service gauge API
(`make_thresholds.py`, stations mapped to NWS gauges in `stations_nws.csv`),
refreshed each run, with `thresholds.json` as the fallback. Gauges read in MLLW
are moved to NAVD88 with Tidewatch's own MLLW-NAVD88 offset for the station.

`.github/workflows/publish.yml` runs `publish.py` at 00:20, 06:20, 12:20 and
18:20 UTC (GitHub may start scheduled runs late) and on demand, then deploys.

Disclaimer: StormSense(TM) Predictive Plots are computer-generated operational
storm tide forecasts; the user assumes any and all risk.

## Forecast guidance switch

`guidance.json` chooses what drives fore72. It is set to `"mode": "override"` with
`"override": "petss"`: P-ETSS at every station, for consistency. Each fore72 chart
names its guidance under the disclaimer, as does the `source` field of each JSON file.
When the adaptive selection from the StormSense ensemble goes live, set `"mode": "adaptive"`
(until then any other setting falls back to the P-ETSS override, with a note in the build log).
