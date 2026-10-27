# StormSense Latest

https://derekloftis.github.io/StormSense-latest/

VIMS StormSense's latest 72-hour storm tide forecasts and gauge observations for every StormSense
station, updated every 6 hours (about 00:20, 06:20, 12:20 and 18:20 UTC):

- `fore72/<ST>_fore72_<MLLW|NAVD>.html|csv|json`: the 72-hour StormSense forecast, its 10–90% uncertainty
  cone, the chance of reaching each NWS flood stage, and labelled forecast high waters (XHW)
- `7day/` and `30day/`: the gauge's own observations, astronomical tide and residual
- `metadata/`: field descriptions (PDF and JSON); `latest.json`, `thresholds.json`, `build_log.txt`

The published files live on the [`site` branch](../../tree/site); `main` only holds this README and the
workflow that deploys the site to GitHub Pages. The pages are self-contained (jQuery and Highcharts are
served from the site's own `jslib/`), so a downloaded copy opens offline.

Disclaimer: StormSense™ Predictive Plots are computer-generated operational storm tide forecasts; the
user assumes any and all risk.
