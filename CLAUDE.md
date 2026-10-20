# StormSense: project knowledge for Claude

This file carries what the original "Tidewatch Charts into StormSense" Claude project learned
about StormSense (Oct 2026), so a new StormSense project can start without it. The same file
sits in DerekLoftis/StormSense-latest and DerekLoftis/StormSense-ensemble. Supporting material
copied out of that project's shared folder (skill code, baselines, notes, station sheet,
disclosures) is in the private repo DerekLoftis/StormSense-archive under `handoff/`
(see `handoff/README.md` there); paths below starting with `handoff/` are in that repo.

## People and goal

- Owner: Derek (Jon Derek Loftis), research assistant professor at VIMS (William & Mary). Writes in English.
- StormSense is VIMS's storm tide forecast and sensor service. It grew out of Tidewatch
  (John Boon's harmonic tide + ETSS surge system on web4.vims.edu, which the old project keeps).
- Goal of this project: archive every StormSense forecast separately from Tidewatch, then develop
  StormSense's own 72-hour forecast instead of only republishing or ensembling existing guidance.

## What is live (all on GitHub Actions, independent of any Claude project)

| Repo | Site | Schedule (UTC) | Archive |
|---|---|---|---|
| DerekLoftis/StormSense-latest (public) | https://derekloftis.github.io/StormSense-latest/ | `publish.yml` 00:20/06:20/12:20/18:20 | none yet (fixed paths, overwritten) |
| DerekLoftis/StormSense-ensemble (public) | https://derekloftis.github.io/StormSense-ensemble/ | `ensemble.yml` 00:40/06:40/12:40/18:40 | one `ensemble_<cycle>.tar.gz` per run on release `ensemble-YYYY-MM` (since 2026-10-16) |

GitHub cron starts late or skips sometimes; there is no fallback. Pages source is "GitHub Actions".
`SCHEDULE` strings in publish.py / ensemble.py must match the workflow cron.

### StormSense Latest (`publish.py`, `products.py`, `petss.py`, `styler/`)
- Products: `fore72/`, `7day/`, `30day/`, files `<ST>_<prod>_<MLLW|NAVD>.html|csv|json`, 35 stations.
- fore72 = NWS P-ETSS (NOMADS, newest GOOD cycle; NOMADS keeps 2 days): hourly surge/bias low-passed
  (3 h Hann) onto P-ETSS 6-min tide, 72 h, aligned to the gauge by the median gap over the prior 24 h
  ("est" sites differ up to 0.75 ft). 10-90% cone in StormSense dark blue rgba(20,38,96,0.5). No m30 line.
  Stations without a P-ETSS point fall back to Tidewatch's 36 h.
- 7day/30day = gauge observations **taken from Tidewatch's web4 3d/30d files** plus P-ETSS / CO-OPS tide.
  StormSense therefore still depends on web4 for most observations (see Roadmap).
- CSV/JSON fields carry units: fore72 `date_time_z, astro_tide_ft, surge_ft, bias_ft, residual_ft,
  SSforecast_ft, SSforecast_p10_ft, SSforecast_p90_ft, surge_p10_ft, surge_p90_ft`; 7day/30day
  `date_time_z, water_level_ft, astro_tide_ft, residual_ft`. Every CSV has a .json twin (metadata header
  + records, null for blanks). Metadata PDFs + JSON in `metadata/` (tools/make_metadata.py; Liberation
  Sans). Derek said to stop tweaking the PDFs.
- `guidance.json` picks fore72's guidance: `"mode": "adaptive"` (Derek, 2026-10-20: turn phase 2 on once there
  is enough history) reads the ensemble's `skill/pick.json` from its Pages site and, per station and lead band,
  follows the picked member's published ens72 series (eased over 1 h at band edges; P-ETSS cone and surge shifted
  with it). Pick older than 18 h, unreachable, or not ready: P-ETSS. `"mode": "override", "override": "petss"`
  forces P-ETSS. Each chart names its guidance under the disclaimer and in JSON `source`.
- Flood thresholds: `make_thresholds.py` from the NWPS gauge API (`stations_nws.csv`), fallback
  `thresholds.json`. Colors Action #FFFF00, Minor #FF9900, Moderate #FF0000, Major #CC33FF.
- web4 sometimes serves empty/partial pages; publish retries and skips them. `build_log.txt` is
  published with the site; a failed build posts its log tail as a "build failed" check-run annotation.

### StormSense Ensemble (`ensemble.py`, `members.py`, `petss.py`, `etss.py`, `psurge.py`, `pages.py`)
- `ens72/<ST>_ens72_<MLLW|NAVD>.html|csv|json`, one column per member; `latest.json` lists run times and
  per-station alignment shifts. `stations.csv` lists 51 stations and model coverage.
- Members: P-ETSS mean + cone, STOFS-2D, STOFS-3D (12Z), CBOFS, NWM short and medium, NWS official (NWPS),
  Tidewatch f36 px30, tide-plus-persistence baseline, ETSS (tgftp FQUS23 KWNO bulletin added to P-ETSS
  tide, 9-11 stations; NOMADS ETSS is 403 from Actions; runs high, e.g. SWPT 4.3 vs P-ETSS 3.6 ft), NHC
  P-Surge e50 (17 stations, only while NHC advisories are out). Details: README.md, NEW_MEMBERS.md.
- Alignment: median(obs - member) over the last 24 h of overlap (>=30 six-minute obs), newest run with the
  previous one stitched in front. NWS and Tidewatch are not shifted.
- Design and phases: `handoff/ensemble_design.md`. Phase 1 (StormSense-ensemble) is live. Phase 2 is built:
  `skill.py` (step in ensemble.yml, continue-on-error) scores every archived run x station x member x lead band
  (0-12/12-36/36-72, plus 0-36/0-72) with Derek's formula against observed_ft stitched across the archived runs,
  once the band has passed (>=85% coverage); cumulative `skill_scores.csv.gz` + `skill_runs.csv` ride on the
  month's `ensemble-YYYY-MM` release; Pages `skill/` has index.html, scores.csv (31 d), summary.csv/json
  (10-day recent skill, e-folding 3 d), pick.json, picks_history.csv. Pick: best recent skill, must lead by
  0.01 for 2 updates running; P-ETSS until 7 days of verified runs and >=12 scores (ready ~10-23 for 0-12 h,
  ~10-26 for 36-72 h). Never picked: tidewatch, baseline, tide; stations USSC USAR USCB USNR USSB GS01 USBB
  (another gauge's obs). Phase 3: regime rules (QPF/rivers, NHC advisories, nor'easter winds). Phase 4: analog and
  learned weights from the archive and AWS/IEM backfills.

## Station sources that are not Tidewatch (in both StormSense repos and tidewatch_latest)

`noaa_override.py` is copied in StormSense-latest, StormSense-ensemble and tidewatch_latest; keep the
copies in step (tidewatch_latest stays with the Tidewatch project).
- CBBT 8638901, MNPT 8639348, DAHL 8635027, WADC 8594900: rebuilt from NOAA CO-OPS 6-min obs (MLLW, 31 d),
  27-constituent UTide fit (no Sa/Ssa) to `harmonics/<ST>_hourly.csv.gz` (refit: `python noaa_override.py
  --hourly harmonics`), 36 h = tide + 0.7 x P-ETSS mean surge offset to the last residual. NAVD88 above
  MLLW: CBBT 1.92, MNPT 1.77 (VDatum MDVAchb12), DAHL 1.04, WADC 1.40 (NOAA). Tidewatch's CBBT/MNPT froze
  2022-05-27; Tidewatch's DAHL and WADC series are another gauge's (see aliasing below).
- BRDH (Back River, VIMS radar gauge): THREDDS https://tds.vims.edu/thredds/dodsC/daveAll/drf/Tidewatch/BRDH.nc
  (1-min since 2017; MLLW = 9.71 - value; QC'd), Sewells Point P-ETSS surge, NAVD88 1.63 ft above MLLW.
- USLN-X: FloodVISION-AI webcam water level at Little Neck Creek from https://usgs-ngwos.vims.edu/
  (Streamlit; payload only in the rendered page). Scraped by tidewatch_latest `floodvision.py`
  (workflow floodvision.yml) into `floodvision/USLN-X_YYYY-MM.csv` (NAVD88; model v2 since 2026-10-09).
- CNRC (Accokeek Creek at Crow's Nest): GreenStream/VDEM sensor, vdem.greenstream.io websocket history,
  level NAVD = 5.89 - stage; archived by tidewatch_latest `greenstream.py` to `greenstream/CNRC_YYYY-MM.csv`
  (from Sept 16). Tide fitted to that archive (13 constituents until 6 months), Dahlgren P-ETSS surge,
  NAVD88 0.691 above MLLW. No key needed (the GreenStream API proper needs Derek's key).
- Station ids may contain '-'. **USLN-X and CNRC history lives in tidewatch_latest**; moving those
  scrapers here is a decision for Derek (see Roadmap).

## Datums and station facts

- NOAA stations on NOAA datums (`styler/noaa_datums/<id>.json`); USGS stations plus GS01/GS02 on VDatum
  (`styler/stations_usgs/_datums/`). The 2024 Virginia VDatum releases put NAVD88 ~1 ft too high; corrected
  with an offset to MDVAchb12. Tidewatch's own MLLW-NAVD offsets differ slightly from NOAA's (DAHL 0.12,
  WMPT 0.05, BISH/YRCG 0.04, WACH 0.03 ft). NAVD charts move MLLW gauges with Tidewatch's offset.
- Retired 2026-10-15 (Derek): NN01-NN10, VB01-VB10, USNW, USPF, USSV. `DROP` in publish.py/ensemble.py.
  Never reintroduce them.
- Aliasing: Tidewatch publishes identical obs under several ids (DAHL/USNC/USSC, WADC/USAR/USBK,
  USFM/USCB, USSF/USNR, USHR/USSB, GS01/GS02). DAHL's are New Market Creek's; USSB, USCB, USNR aren't
  their sites; GS01/GS02 is GS02 (Pamunkey). USBB repeats values in ~18-min steps. USLI's f36 px30 is
  empty. Exclude Tidewatch's DAHL/WADC from skill comparisons. Details: `handoff/skill/tidewatch-asa/output/aliasing/`.
- NWPS observation datum shifts vs Tidewatch: WMPT +0.044, YRCG +0.045, BISH -0.036, WACH -0.035 ft.
- Model datum gotchas: STOFS SHEF MLLW ft; NWM SHEF NAVD88 ft and 0.6-0.7 ft low everywhere; CBOFS zeta m
  MSL (nearest node <=3 km); STOFS-2D at USGS LIDs FTMV2, JSFV2, NMDV2 sits 0.7-1.3 ft low.

## Skill scoring (reuse; code in `handoff/skill/tidewatch-asa/`)

- Derek's skill formula for every table, plot and deck: S = 0.25[R² + e^(-|Bias|/σ) + e^(-MAE/σ) +
  e^(-RMSE/σ)], σ = population SD of obs in the window; 0-1, 3 decimals, no-skill ~0.45, storm ~0.67,
  calm ~0.75. Site Skill uses the 30-day SD and CRITIC weights. Derek hasn't answered the proposal to
  merge MAE/RMSE and weight R² least; don't change the formula without him.
- Known results: Sept 2026 36-h RMSE NWS 0.24 vs Tidewatch 0.28 ft (NWS better at 10 of 11; nor'easter
  0.29 vs 0.52). King tide 8-12 Oct 2026: NWS 0.21, Tidewatch 0.26, STOFS-2D 0.18 (vs TW 0.22), CBOFS 0.25,
  STOFS-3D 0.31 (bias -0.25), NWM 0.73. First ensemble scores (runs 16-18 Oct 2026, ~1.5 ft surge event,
  mean over stations): 0-12 h RMSE ETSS 0.24, Tidewatch 0.25, STOFS-2D 0.27, P-ETSS 0.32 ft; 36-72 h STOFS-3D
  0.65, STOFS-2D 0.70, P-ETSS 0.86 ft (bias +0.77, everyone high); P-ETSS 10-90% cone held 33% of obs at 0-12 h.
- Event look-backs use Derek's deck format (`handoff/notes/flood-event-validation-format.md`): pptx with
  autoplay mp4 per forecast, station stats table first, ROYGBIV forecast colors, halo-labelled composite.

## Style rules (Derek's)

- StormSense logo, cyan #00E5EE residual, header "StormSense Latest Forecasts and Sensor Observations".
- Disclaimer on every chart: "StormSense(TM) Predictive Plots are computer-generated operational storm
  tide forecasts; the user assumes any and all risk." Guidance name goes on the line below it.
- MLLW charts: gray datum lines (HAT+n ... LAT, NAVD88). NAVD charts: NWPS Action/Minor/Moderate/Major plus
  the MLLW line. Line labels click to hide/show. Pages are self-contained (libraries inlined in `styler/jslib`)
  because Derek's browser hung on CDN scripts. Tidewatch charts keep VIMS teal #16687E m30 and their own
  disclaimer; don't mix the brands.
- Disclosures (PDF + html source): `handoff/disclosures/` (one "[Derek: confirm]" on GOES telemetry).

## Network and platform limits

- Use Derek's default cloud environment (the one that reaches web4, api.water.noaa.gov, api.weather.gov,
  NOMADS). No Claude session reaches tidesandcurrents.noaa.gov or *.github.io; NOAA AWS buckets work.
- GitHub Actions has full internet (except NOMADS ETSS paths, 403), so put blocked downloads in a
  workflow. Read live pages from a workflow, not the sandbox; job logs and artifacts aren't readable
  from the sandbox, but check-run annotations are.
- Claude sessions can't create repos, buckets, releases (from the sandbox), delete branches or change repo
  settings: do release uploads inside workflows; ask Derek for the rest. Dispatching a workflow needs Derek's yes.

## Roadmap for the StormSense project (suggested order)

1. **Archive StormSense Latest** separately from Tidewatch: every cycle's fore72/7day/30day CSV+JSON (and
   html) as one tarball per cycle on monthly releases `stormsense-YYYY-MM` in DerekLoftis/StormSense-archive,
   plus an index CSV. Simplest with no secrets: a scheduled workflow in StormSense-archive (e.g. :50 past
   00/06/12/18) downloads the just-published public Pages files and uploads to its own releases with
   `github.token`. (Uploading from StormSense-latest instead would need a token secret for the other repo.)
2. Verify P-ETSS and every ensemble member with the skill code against obs as the archive grows.
3. Phase 2 adaptive pick (skill per station and lead band, hysteresis): built (skill.py, guidance.json adaptive).
4. **StormSense's own 72-h forecast**: own harmonic tide per gauge (UTide, as noaa_override.py does),
   own observations (CO-OPS, USGS NWIS, THREDDS, GreenStream, FloodVISION) so web4 is no longer needed,
   and a surge model of StormSense's own, e.g. a skill-weighted blend or a regression/ML correction of
   member surges using recent residual, wind, pressure, QPF and river flow, trained on the archives
   (ensemble releases, tidewatch_archive model/NWPS releases, AWS STOFS/NWM history, IEM NWS HML).
   Publish it as its own member first, and let the adaptive pick choose it only once it scores best.
5. Embeddable interactive archive viewer (iframe for pages like
   https://www.vims.edu/people/loftis_jd/StormSense/forecasts/noaa/swpt/): needs a public-read Cloudflare
   R2 or VIMS S3 bucket with its key as repo secrets (Derek creates).

## Where the history lives

- Ensemble runs since 2026-10-16: StormSense-ensemble's `ensemble-YYYY-MM` releases.
- Tidewatch f36/3d/30d, Classic, NWPS, NWS CFW and STOFS/NWM/CBOFS model files since 16 Sept 2026: private
  DerekLoftis/tidewatch_archive, releases `archive-YYYY-MM` (one tarball per run; index CSVs in the repo
  under `data/index/`), plus `nws-backfill` (IEM NWS HML for Sept 2026, Oct 2025, Oct 2016) and
  `reference-data` (NOAA datums, VDatum grids).
- USLN-X and CNRC observation archives: DerekLoftis/tidewatch_latest `floodvision/`, `greenstream/`.
- The old project's ASA outputs (decks, animations, papers) stay in that project's shared folder.
