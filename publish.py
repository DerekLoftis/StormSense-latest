"""Build the StormSense Latest site: copy the newest Tidewatch charts and CSVs
(placeholders until StormSense's own products exist), restyle the charts for
StormSense, and write them to fixed paths under site/ for GitHub Pages.

    python publish.py [site_dir] [work_dir]

    site/fore72/<ST>_fore72_{MLLW,NAVD}.{html,csv}   forecast, 72 h planned (Tidewatch f36 for now)
    site/7day/<ST>_7day_{MLLW,NAVD}.{html,csv}       recent observations (Tidewatch 3d)
    site/30day/<ST>_30day_{MLLW,NAVD}.{html,csv}     30-day observations (Tidewatch 30d)

MLLW charts get the tidal datum lines; NAVD charts get the MLLW line and the
NWS flood categories from thresholds.json (refreshed from NWPS each run when
reachable). Nothing is archived: each run replaces the last.
"""

import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone

TIDEWATCH_URL = os.environ.get("TIDEWATCH_URL", "https://web4.vims.edu/physical/tidewatch/")
UA = {"User-Agent": "stormsense-latest (VIMS)"}
HERE = os.path.dirname(os.path.abspath(__file__))
# Tidewatch product -> StormSense name
PRODUCTS = {"f36": "fore72", "3d": "7day", "30d": "30day"}
LABELS = {"fore72": "Forecast", "7day": "7-day observations", "30day": "30-day observations"}
# The Tidewatch NAVD chart page has no datum in its name (SWPT_2018_f36_hc.html).
NAME = re.compile(r"^([A-Z0-9]+)_\d{4}_(f36|3d|30d)(?:_(MLLW|NAVD))?(_hc\.html|\.csv)$")
PICKLE = re.compile(r"^[A-Z0-9]+_\d{4}_f36\.pypickle$")
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
    names = sorted(n for n in hrefs if NAME.match(n) or PICKLE.match(n))
    if not any(NAME.match(n) for n in names):
        sys.exit("no Tidewatch files found in the listing")
    failed = []
    for n in names:
        prod = "f36" if PICKLE.match(n) else NAME.match(n).group(2)
        os.makedirs(os.path.join(raw, prod), exist_ok=True)
        try:
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
                            "--thresholds=" + thresholds, "--navdlines=mllw"],
                           capture_output=True, text=True)
        print((r.stdout + r.stderr).strip()[-2000:])
        if r.returncode == 0:
            for n in os.listdir(out):
                shutil.copy(os.path.join(out, n), os.path.join(src, n))


def place(raw, site):
    """Copy raw/<tidewatch product>/ into site/<StormSense product>/ under the new names."""
    stations = {}
    for tw, prod in PRODUCTS.items():
        src = os.path.join(raw, tw)
        if not os.path.isdir(src):
            continue
        os.makedirs(os.path.join(site, prod), exist_ok=True)
        for n in sorted(os.listdir(src)):
            m = NAME.match(n)
            if not m:
                continue
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
    return stations


def main(site="site", work="work"):
    raw = os.path.join(work, "raw")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    failed = fetch(raw)
    thresholds = refresh_thresholds(work)
    style(raw, work, thresholds)
    stations = place(raw, site)
    os.makedirs(os.path.join(site, "jslib"), exist_ok=True)
    for f in os.listdir(os.path.join(HERE, "styler", "jslib")):
        shutil.copy(os.path.join(HERE, "styler", "jslib", f), os.path.join(site, "jslib", f))
    shutil.copy(os.path.join(HERE, "styler", "stormsense_logo.png"), os.path.join(site, "jslib"))
    shutil.copy(os.path.join(HERE, "stormsense_logo.png"), site)
    shutil.copy(thresholds, os.path.join(site, "thresholds.json"))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    write_index(site, stations, json.load(open(thresholds)), now)
    with open(os.path.join(site, "latest.json"), "w") as f:
        json.dump({"updated": now, "source": TIDEWATCH_URL, "files": sum(len(v) for v in stations.values()),
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
            links = " ".join(f'<a href="{html.escape(u)}">{t}</a>' for u, t in ((h, "chart"), (c, "csv")) if u)
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
<p class="disc">NAVD88 charts show the NWS flood categories (Action, Minor, Moderate, Major) from the
National Water Prediction Service and the MLLW line; MLLW charts show the tidal datums. Click a line's label
on the right of a chart to hide or show it.</p>
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
