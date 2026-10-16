"""Build the StormSense Latest site: the 72-hour forecast from NWS P-ETSS and the
gauge observations Tidewatch publishes, restyled for StormSense and written to
fixed paths under site/ for GitHub Pages.

    python publish.py [site_dir] [work_dir]

    site/fore72/<ST>_fore72_{MLLW,NAVD}.{html,csv}   72-hour forecast from P-ETSS with its 10-90%
                                                     cone (Tidewatch's 36-hour forecast where P-ETSS
                                                     has no point for the station)
    site/7day/<ST>_7day_{MLLW,NAVD}.{html,csv}       last 7 days of observations (Tidewatch 30d + 3d)
                                                     with the P-ETSS / CO-OPS tide and residual
    site/30day/<ST>_30day_{MLLW,NAVD}.{html,csv}     last 30 days, likewise

MLLW charts get the tidal datum lines; NAVD charts get the MLLW line and the
NWS flood categories from thresholds.json (refreshed from NWPS each run when
reachable). Nothing is archived: each run replaces the last.
"""

import csv
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

TIDEWATCH_URL = os.environ.get("TIDEWATCH_URL", "https://web4.vims.edu/physical/tidewatch/")
UA = {"User-Agent": "stormsense-latest (VIMS)"}
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import petss  # noqa: E402
import products  # noqa: E402
# Tidewatch product -> StormSense name
PRODUCTS = {"f36": "fore72", "3d": "7day", "30d": "30day"}
LABELS = {"fore72": "72-hour forecast", "7day": "7-day observations", "30day": "30-day observations"}
# The Tidewatch NAVD chart page has no datum in its name (SWPT_2018_f36_hc.html).
NAME = re.compile(r"^([A-Z0-9]+)_\d{4}_(f36|3d|30d)(?:_(MLLW|NAVD))?(_hc\.html|\.csv)$")
PICKLE = re.compile(r"^[A-Z0-9]+_\d{4}_f36\.pypickle$")
# Retired or unusable Tidewatch stations, left out of StormSense (Derek, 2026-10-15): NN01-NN10 and
# VB01-VB10 have not updated in over a year; USNW, USPF and USSV are non-tidal or lack needed data.
DROP = re.compile(r"^(NN\d\d|VB\d\d|USNW|USPF|USSV)_")
SCHEDULE = "00:20, 06:20, 12:20 and 18:20 UTC"  # keep in step with .github/workflows/publish.yml


def get(url, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return r.read()
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(5 * (i + 1))


def fetch(raw):
    """Download the current Tidewatch files into raw/<tidewatch product>/."""
    listing = get(TIDEWATCH_URL).decode("utf-8", "replace")
    hrefs = set(re.findall(r'href="([^"?/]+)"', listing))
    names = sorted(n for n in hrefs if (NAME.match(n) or PICKLE.match(n)) and not DROP.match(n))
    if not any(NAME.match(n) for n in names):
        sys.exit("no Tidewatch files found in the listing")
    failed = []
    for n in names:
        prod = "f36" if PICKLE.match(n) else NAME.match(n).group(2)
        os.makedirs(os.path.join(raw, prod), exist_ok=True)
        try:
            data = get(TIDEWATCH_URL + n)
            if n.endswith("_hc.html") and b"var data = " not in data:  # web4 sometimes serves a partial page
                time.sleep(5)
                data = get(TIDEWATCH_URL + n)
        except Exception as e:
            failed.append(f"{n}: {e}")
            continue
        with open(os.path.join(raw, prod, n), "wb") as f:
            f.write(data)
    return failed


def refresh_thresholds(work):
    """NWS flood categories from NWPS; the committed thresholds.json if NWPS is down."""
    out = os.path.join(work, "thresholds.json")
    r = subprocess.run([sys.executable, os.path.join(HERE, "make_thresholds.py"), out],
                       capture_output=True, text=True)
    print(r.stdout.strip() or r.stderr.strip())
    if r.returncode or not os.path.exists(out):
        shutil.copy(os.path.join(HERE, "thresholds.json"), out)
        print("using the committed thresholds.json")
    return out


COOPS = ("https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?product=predictions&station={id}"
         "&begin_date={a:%Y%m%d}&end_date={b:%Y%m%d}&datum=MLLW&units=english&time_zone=gmt&interval=6&format=json")


def coops_tide(nos_id, days=32):
    """{datetime: tide} from NOAA CO-OPS 6-minute predictions (MLLW, ft); P-ETSS uses the same harmonics."""
    b = datetime.now(timezone.utc) + timedelta(days=1)
    js = json.loads(get(COOPS.format(id=nos_id, a=b - timedelta(days=days), b=b)))
    return {datetime.strptime(p["t"], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc): float(p["v"])
            for p in js.get("predictions", [])}


def guidance():
    """The guidance setting in guidance.json. Only the P-ETSS override exists so far; 'adaptive'
    will read each station's pick from the StormSense ensemble once that goes live."""
    g = json.load(open(os.path.join(HERE, "guidance.json")))
    if g.get("mode") != "override" or g.get("override") != "petss":
        print(f"guidance {g.get('mode')}/{g.get('override')} is not available yet; using the P-ETSS override")
    return {"mode": "override", "source": "petss"}


def transform(raw):
    """Build the StormSense products from the Tidewatch files and P-ETSS (see products.py)."""
    guide = guidance()
    lids = {r["tidewatch_id"]: r["nws_lid"] for r in csv.DictReader(open(os.path.join(HERE, "stations_nws.csv")))}
    pet, cycle, older = {}, None, None
    try:
        cycle, a, b = petss.newest_cycle()
        pet = petss.load(cycle, a, b, set(lids.values()))
        print(f"P-ETSS {cycle:%Y-%m-%d %HZ}: {len(pet)} NWS gauges")
        oc, older = petss.oldest_csv(cycle)
        series = petss.tide_series([older, a])
        print(f"P-ETSS tide back to the {oc:%Y-%m-%d %HZ} cycle's hindcast" if oc else "P-ETSS: no older cycle")
    except Exception as e:
        print("P-ETSS unavailable:", e)
        series = {}
    done, adjs, offs = products.fore72(raw, lids, pet, cycle)
    print(f"fore72 from P-ETSS: {len(done)} files ({', '.join(done)})")
    print(f"7day: {products.seven_day(raw)} pages")
    tides, coops = {}, []
    for st, adj in adjs.items():
        sid = pet[lids[st]]["id"]
        tide = {}
        if sid.isdigit():  # NOAA station: CO-OPS predictions reach the full 30 days
            try:
                tide.update(coops_tide(sid))
                coops.append(st)
            except Exception as e:
                print(f"  CO-OPS {sid} ({st}): {e}")
        pt = series.get(sid, {})
        both = [t for t in pt if t in tide]
        if both:
            print(f"  {st}: CO-OPS minus P-ETSS tide, max |diff| {max(abs(tide[t] - pt[t]) for t in both):.3f} ft over {len(both)} points")
        tide.update(pt)
        tides[st] = {products.ms(t): v + adj for t, v in tide.items()}
    print(f"astronomic tide for hindcasts: {len(tides)} stations (CO-OPS for {', '.join(coops) or 'none'})")
    print(f"hindcast charts with tide and residual: {products.hindcasts(raw, tides, offs)}")
    return {"guidance": guide, "cycle": cycle.strftime("%Y-%m-%dT%HZ") if cycle else None,
            "stations": sorted({d.split()[0] for d in done}),
            "hindcast_tide": sorted(tides), "coops_tide": coops,
            "alignment_ft": {k: round(v, 3) for k, v in adjs.items()}}


def style(raw, work, thresholds):
    """Restyle each product's chart pages; pages that can't be styled stay as Tidewatch's."""
    styler = os.path.join(HERE, "styler")
    for tw in PRODUCTS:
        src = os.path.join(raw, tw)
        if not os.path.isdir(src):
            continue
        out = os.path.join(work, "styled", tw)
        r = subprocess.run([sys.executable, os.path.join(styler, "style_pages.py"), "--product", tw,
                            "--pages", src, "--csv", src, "--pickles", os.path.join(raw, "f36"),
                            "--out", out, "--jsdir=../jslib", "--brand=stormsense",
                            "--thresholds=" + thresholds, "--navdlines=mllw", "--nom30"],
                           capture_output=True, text=True)
        print((r.stdout + r.stderr).strip()[-2000:])
        if r.returncode == 0:
            for n in os.listdir(out):
                shutil.copy(os.path.join(out, n), os.path.join(src, n))


DESCRIBE = {"fore72": "72-hour storm tide forecast", "7day": "7-day observed water level hindcast",
            "30day": "30-day observed water level hindcast"}


def write_json(csv_path, out, st, prod, datum, updated, source):
    """JSON copy of a product CSV: metadata plus one record per row (blank values become null)."""
    with open(csv_path) as f:
        rows = list(csv.reader(f))
    head = rows[0]
    recs = []
    for r in rows[1:]:
        rec = {}
        for h, v in zip(head, r):
            rec[h] = v if h.startswith("date_time") else (float(v) if v not in ("", "nan") else None)
        recs.append(rec)
    meta = f"stormsense-metadata-for-{prod}-csv-data{'-NAVD' if datum == 'NAVD' else ''}.json"
    doc = {"station": st, "product": prod, "description": DESCRIBE[prod],
           "datum": "NAVD88" if datum == "NAVD" else "MLLW", "units": "feet", "time_zone": "UTC (Z)",
           "interval_minutes": 6, "updated": updated, "source": source, "fields": head,
           "metadata": f"../metadata/{meta}", "data": recs}
    with open(out, "w") as f:
        json.dump(doc, f, separators=(",", ":"))


def place(raw, site, updated="", petss_stations=()):
    """Copy raw/<tidewatch product>/ into site/<StormSense product>/ under the new names,
    with a JSON copy of each CSV."""
    stations = {}
    for tw, prod in PRODUCTS.items():
        src = os.path.join(raw, tw)
        if not os.path.isdir(src):
            continue
        os.makedirs(os.path.join(site, prod), exist_ok=True)
        for n in sorted(os.listdir(src)):
            m = NAME.match(n)
            if not m or DROP.match(n) or os.path.getsize(os.path.join(src, n)) == 0:
                continue  # retired station, or an empty file from web4
            st, _, datum, kind = m.groups()
            if datum == "NAVD" and kind == "_hc.html" and os.path.exists(os.path.join(src, n.replace("_NAVD_hc", "_hc"))):
                continue  # stale 30d page; the current NAVD page has no datum in its name
            if datum is None:
                if kind != "_hc.html":
                    continue
                datum = "NAVD"
            ext = ".html" if kind == "_hc.html" else ".csv"
            new = f"{st}_{prod}_{datum}{ext}"
            shutil.copy(os.path.join(src, n), os.path.join(site, prod, new))
            stations.setdefault(st, {})[(prod, datum, ext)] = f"{prod}/{new}"
            if ext == ".csv":
                if prod == "fore72":
                    source = ("NWS P-ETSS (fixed P-ETSS override at all stations)" if st in petss_stations
                              else "VIMS Tidewatch 36-hour forecast (no P-ETSS point for this station)")
                else:
                    source = "gauge observations; astronomical tide from NWS P-ETSS and NOAA CO-OPS predictions"
                write_json(os.path.join(site, prod, new), os.path.join(site, prod, new[:-4] + ".json"),
                           st, prod, datum, updated, source)
                stations[st][(prod, datum, ".json")] = f"{prod}/{new[:-4]}.json"
    return stations


def main(site="site", work="work"):
    raw = os.path.join(work, "raw")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    failed = fetch(raw)
    pet = transform(raw)
    thresholds = refresh_thresholds(work)
    style(raw, work, thresholds)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    stations = place(raw, site, now, set(pet.get("stations", ())))
    os.makedirs(os.path.join(site, "jslib"), exist_ok=True)
    for f in os.listdir(os.path.join(HERE, "styler", "jslib")):
        shutil.copy(os.path.join(HERE, "styler", "jslib", f), os.path.join(site, "jslib", f))
    shutil.copy(os.path.join(HERE, "styler", "stormsense_logo.png"), os.path.join(site, "jslib"))
    shutil.copy(os.path.join(HERE, "stormsense_logo.png"), site)
    shutil.copy(thresholds, os.path.join(site, "thresholds.json"))
    shutil.copytree(os.path.join(HERE, "metadata"), os.path.join(site, "metadata"), dirs_exist_ok=True)
    write_index(site, stations, json.load(open(thresholds)), now)
    with open(os.path.join(site, "latest.json"), "w") as f:
        json.dump({"updated": now, "source": TIDEWATCH_URL, "files": sum(len(v) for v in stations.values()), "petss": pet,
                   "failed": failed}, f, indent=1)
    open(os.path.join(site, ".nojekyll"), "w").close()
    print(f"{sum(len(v) for v in stations.values())} files for {len(stations)} stations; {len(failed)} failed")
    for x in failed:
        print("  failed:", x)


def write_index(site, stations, flood, now):
    cols = [(p, d) for p in PRODUCTS.values() for d in ("MLLW", "NAVD")]
    head1 = "".join(f'<th colspan="2">{LABELS[p]}<br><span class="code">{p}</span></th>' for p in PRODUCTS.values())
    head2 = "".join(f"<th>{d}</th>" for _, d in cols)
    rows = []
    for st in sorted(stations):
        cells = []
        for p, d in cols:
            h = stations[st].get((p, d, ".html"))
            c = stations[st].get((p, d, ".csv"))
            j = stations[st].get((p, d, ".json"))
            links = " ".join(f'<a href="{html.escape(u)}">{t}</a>' for u, t in ((h, "chart"), (c, "csv"), (j, "json")) if u)
            cells.append(f"<td>{links}</td>")
        t = flood.get(st)
        nws = (f'<a href="https://water.noaa.gov/gauges/{t["lid"]}">{t["lid"]}</a>' if t else "")
        rows.append(f"<tr><th>{st}</th>{''.join(cells)}<td>{nws}</td></tr>")
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>StormSense Latest</title>
<style>
body{{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;margin:0 auto;padding:16px;max-width:1100px;color:#1b2533;background:#fff}}
header img{{width:min(520px,100%);height:auto;display:block}}
h1{{font-size:1.5rem;margin:12px 0 4px;color:#14285a}}
p{{margin:6px 0;line-height:1.45}}
.disc{{color:#555;font-size:.92rem}}
.wrap{{overflow-x:auto;margin-top:14px}}
table{{border-collapse:collapse;font-size:.92rem}}
th,td{{border:1px solid #d5dbe3;padding:4px 8px;text-align:left;white-space:nowrap}}
thead th{{background:#eef6fa;text-align:center}}
.code{{font-family:ui-monospace,monospace;font-weight:normal;color:#555}}
a{{color:#0d6e8a}}
</style></head>
<body><header><img src="stormsense_logo.png" alt="StormSense: Forecasting Flooding from Storm Surge, Rain, &amp; Tides"></header>
<h1>StormSense Latest Forecasts and Sensor Observations</h1>
<p>Updated every 6 hours; updated {now}. Links maintain the same address and are overwritten upon each
update at about {SCHEDULE}.</p>
<p class="disc">Disclaimer: StormSense&trade; Predictive Plots are computer-generated operational storm tide
forecasts; the user assumes any and all risk.</p>
<p class="disc">Forecasts come from the NWS Probabilistic Extra-Tropical Storm Surge model (P-ETSS),
interpolated to 6 minutes; the shaded cone is its 10%&ndash;90% range. Stations without a P-ETSS point
show Tidewatch's 36-hour forecast for now.</p>
<p class="disc">NAVD88 charts show the NWS flood categories (Action, Minor, Moderate, Major) from the
National Water Prediction Service and the MLLW line; MLLW charts show the tidal datums. Click a line's label
on the right of a chart to hide or show it.</p>
<p class="disc">Field descriptions for the CSV and JSON downloads: fore72: MLLW <a href="metadata/stormsense-metadata-for-fore72-csv-data.pdf">PDF</a> <a href="metadata/stormsense-metadata-for-fore72-csv-data.json">JSON</a>, NAVD88 <a href="metadata/stormsense-metadata-for-fore72-csv-data-NAVD.pdf">PDF</a> <a href="metadata/stormsense-metadata-for-fore72-csv-data-NAVD.json">JSON</a>; 7day: MLLW <a href="metadata/stormsense-metadata-for-7day-csv-data.pdf">PDF</a> <a href="metadata/stormsense-metadata-for-7day-csv-data.json">JSON</a>, NAVD88 <a href="metadata/stormsense-metadata-for-7day-csv-data-NAVD.pdf">PDF</a> <a href="metadata/stormsense-metadata-for-7day-csv-data-NAVD.json">JSON</a>; 30day: MLLW <a href="metadata/stormsense-metadata-for-30day-csv-data.pdf">PDF</a> <a href="metadata/stormsense-metadata-for-30day-csv-data.json">JSON</a>, NAVD88 <a href="metadata/stormsense-metadata-for-30day-csv-data-NAVD.pdf">PDF</a> <a href="metadata/stormsense-metadata-for-30day-csv-data-NAVD.json">JSON</a>.</p>
<div class="wrap"><table><thead><tr><th rowspan="2">Station</th>{head1}<th rowspan="2">NWS gauge</th></tr>
<tr>{head2}</tr></thead>
<tbody>
{chr(10).join(rows)}
</tbody></table></div></body></html>
"""
    with open(os.path.join(site, "index.html"), "w") as f:
        f.write(page)


if __name__ == "__main__":
    main(*sys.argv[1:])
