"""Turn the Tidewatch placeholder files into StormSense products, in place in
the raw Tidewatch folders (publish.py renames them afterwards):

  fore72  P-ETSS 72-hour forecast (6-minute, with a 10-90% uncertainty cone)
          wherever P-ETSS covers the station's NWS gauge; elsewhere Tidewatch's
          36-hour forecast. CSV fields in F72_HEAD.
  7day    the last 7 days, from the 30-day hindcast plus the newer 3-day one.
  30day   the 30-day hindcast.
  Hindcast CSV fields in HC_HEAD.
"""
import csv
import json
import os
import re
from datetime import datetime, timedelta, timezone

import numpy as np

import petss

DATA = re.compile(r"var data = (\[.*?\]);\n", re.S)
UTC = re.compile(r"Date\.UTC\((\d+),(\d+),(\d+),(\d+),(\d+),(\d+)(?:,[\d.]+)?\)")
CONE = "rgba(20, 38, 96, 0.5)"  # dark blue of the StormSense logo, 50% transparent
# fore72 CSV: P-ETSS keys -> fields (low/high are the 10th/90th percentiles, i.e. P-ETSS's 90%
# and 10% exceedance levels)
F72_KEYS = ("astro_tide", "surge", "bias", "residual", "SSforecast", "low", "high", "surge_low", "surge_high")
F72_HEAD = ["date_time_z", "astro_tide_ft", "surge_ft", "bias_ft", "residual_ft", "SSforecast_ft",
            "SSforecast_p10_ft", "SSforecast_p90_ft", "surge_p10_ft", "surge_p90_ft"]
HC_HEAD = ["date_time_z", "water_level_ft", "astro_tide_ft", "residual_ft"]
LEVELS = {"astro_tide", "SSforecast", "low", "high"}  # water levels (move with the datum)
RENAME = {"Astronomic (m30)": "Astronomic Tide", "Astronomic (m30) Forecast": "Astronomic Tide Forecast",
          "36hr Forecast": "StormSense Forecast"}


# --- Highcharts pages --------------------------------------------------------
def read_page(path):
    html = open(path, encoding="utf-8").read()
    m = DATA.search(html)
    if not m:  # a truncated or empty Tidewatch page: leave it as it is
        print(f"  no chart data in {os.path.basename(path)}")
        return html, []
    js = UTC.sub(lambda u: str(int(datetime(int(u[1]), int(u[2]) + 1, int(u[3]), int(u[4]), int(u[5]), int(u[6]),
                                            tzinfo=timezone.utc).timestamp() * 1000)), m.group(1))
    return html, json.loads(js)


# Guidance line drawn under the disclaimer on fore72 charts (publish.py may replace these).
GUIDANCE = {"petss": "Forecast guidance: NWS P-ETSS ensemble mean (fixed P-ETSS override at all stations)",
            "tidewatch": "Forecast guidance: VIMS Tidewatch 36-hour forecast (no P-ETSS point for this station)"}
GUIDE = re.compile(r"<script>var ssGuidance = .*?;</script>\n?")
# JSON "source" of a fore72 file
SOURCE = {"petss": "NWS P-ETSS (fixed P-ETSS override at all stations)"}
# Members the adaptive pick may choose (StormSense Ensemble keys), as named on the chart
MEMBER_NAMES = {"petss": "NWS P-ETSS", "stofs2d": "NOAA STOFS-2D-Global", "stofs3d": "NOAA STOFS-3D-Atlantic",
                "cbofs": "NOAA CBOFS", "nwm_short": "NWM coastal (short range)",
                "nwm_medium": "NWM coastal (medium range)", "etss": "NWS ETSS", "psurge": "NHC P-Surge (50%)",
                "nws": "NWS official forecast", "stormsense": "StormSense"}
BANDS = (("0-12", 0, 12), ("12-36", 12, 36), ("36-72", 36, 72))
BLEND_STEPS = 11  # 1-hour running mean that eases each change of guidance
ENS_MAX_AGE = timedelta(hours=18)
_ens = {}


def write_page(path, html, series, title=None, guidance=None):
    if guidance:  # read by the styler, which writes it under the disclaimer
        html = GUIDE.sub("", html).replace("</head>", "<script>var ssGuidance = %s;</script>\n</head>"
                                           % json.dumps(guidance), 1)
    html = DATA.sub(lambda m: "var data = " + json.dumps(series, separators=(",", ":")) + ";\n", html, count=1)
    if title:
        html = re.sub(r'("title": \{"text": ")[^"]*(")', lambda m: m.group(1) + title + m.group(2), html, count=1)
    open(path, "w", encoding="utf-8").write(html)


def rename_series(series):
    for s in series:
        s["name"] = RENAME.get(s["name"], s["name"])
    return series


def ms(t):
    return int(t.timestamp() * 1000)


def pts(times, vals):
    return [[ms(t), round(float(v), 3)] for t, v in zip(times, vals) if not np.isnan(v)]


# --- CSV ---------------------------------------------------------------------
def read_csv(path):
    with open(path, newline="") as f:
        rows = list(csv.reader(f))
    return rows[0], rows[1:]


def write_csv(path, head, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(head)
        w.writerows(rows)


def fmt(v):
    return "" if v is None or np.isnan(v) else "%.3f" % (round(v, 3) + 0.0)


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_t(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def offset(f36_dir, st):
    """Tidewatch's MLLW minus NAVD for the station (median over its f36 pair)."""
    try:
        a = dict(r[:4:3] for r in read_csv(os.path.join(f36_dir, f"{st}_2018_f36_MLLW.csv"))[1])
        b = dict(r[:4:3] for r in read_csv(os.path.join(f36_dir, f"{st}_2018_f36_NAVD.csv"))[1])
        d = sorted(float(a[t]) - float(b[t]) for t in a.keys() & b.keys() if a[t] and b[t])
        return d[len(d) // 2] if d else None
    except Exception:
        return None


# --- fore72 ------------------------------------------------------------------
def ensemble_series(url, st):
    """{epoch ms: {member: ft MLLW}} from the StormSense Ensemble's published ens72 JSON, or None."""
    if st not in _ens:
        _ens[st] = None
        try:
            import urllib.request
            req = urllib.request.Request(f"{url}ens72/{st}_ens72_MLLW.json", headers={"User-Agent": "stormsense-latest (VIMS)"})
            with urllib.request.urlopen(req, timeout=60) as r:
                doc = json.loads(r.read())
            age = datetime.now(timezone.utc) - datetime.strptime(doc["updated"], "%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)
            if age > ENS_MAX_AGE:
                raise ValueError(f"ensemble file is {age} old")
            _ens[st] = {ms(parse_t(r["date_time_z"])): r for r in doc["data"]}
        except Exception as e:
            print(f"  {st}: ensemble series unavailable ({e}); P-ETSS kept")
    return _ens[st]


def adapt(f, st, guide, base=None):
    """Phase 2 adaptive guidance. Where the ensemble's skill pick for this station and lead band
    (hours after t0) is another member, the forecast follows that member as published on the
    ensemble chart (the series that was scored); the change from P-ETSS is eased over an hour at
    each band edge, and the P-ETSS cone and surge move with it. base: the station's P-ETSS
    guidance line. Returns (f, chart line, JSON source)."""
    base = base or GUIDANCE["petss"]
    if guide.get("mode") != "adaptive":
        return f, base, SOURCE["petss"]
    picks = guide["pick"].get("stations", {}).get(st, {})
    ready = [b for b, _, _ in BANDS if picks.get(b, {}).get("ready")]
    chosen = {b: picks[b]["member"] for b in ready if picks[b]["member"] != "petss" and picks[b]["member"] in MEMBER_NAMES}
    why = "best recent skill" if ready else "until a week of skill history exists"
    plain = ((f"Forecast guidance: NWS P-ETSS ensemble mean (adaptive pick: {why})" if base == GUIDANCE["petss"]
              else f"{base}; adaptive pick: P-ETSS {why}"), f"NWS P-ETSS (adaptive pick: {why})")
    if not chosen:
        return f, *plain
    ens = ensemble_series(guide["ensemble_url"], st)
    if not ens:
        return f, *plain
    lead = np.array([(t - f["time"][0]).total_seconds() / 3600 for t in f["time"]])
    delta = np.zeros(len(lead))
    used = {}
    for band, lo, hi in BANDS:
        m = chosen.get(band)
        if not m:
            continue
        for i in np.where((lead > lo if lo else lead >= lo) & (lead <= hi))[0]:
            v = ens.get(ms(f["time"][i]), {}).get(f"{m}_ft")
            if v is not None and not np.isnan(f["SSforecast"][i]):
                delta[i] = v - f["SSforecast"][i]
                used.setdefault(band, m)
    if not used:
        return f, *plain
    k = np.ones(BLEND_STEPS)
    delta = np.convolve(delta, k, "same") / np.convolve(np.ones(len(delta)), k, "same")
    for key in ("SSforecast", "low", "high", "surge", "surge_low", "surge_high"):
        f[key] = f[key] + delta
    f["residual"] = f["SSforecast"] - f["astro_tide"]
    parts = ", ".join(f"{MEMBER_NAMES[used.get(b, 'petss')]} {b} h" for b, _, _ in BANDS)
    return (f, f"Forecast guidance: {parts} (adaptive pick by recent skill; shaded cone: P-ETSS 10-90% spread)",
            f"adaptive pick by recent skill: {parts}; cone and surge: NWS P-ETSS shifted to the picked forecast")


def fore72(raw, lids, pet, cycle, guide=None):
    """Rewrite raw/f36 pages and CSVs. lids: {ST: NWS id}; pet: {NWS id: P-ETSS station};
    guide: publish.guidance(). Returns (done, alignments, MLLW-NAVD offsets, JSON sources)."""
    guide = guide or {"mode": "override"}
    d = os.path.join(raw, "f36")
    done, adjs, sources = [], {}, {}
    offs = {n.split("_")[0]: offset(d, n.split("_")[0]) for n in os.listdir(d) if n.endswith("_f36_NAVD.csv")}
    for name in sorted(os.listdir(d)):
        m = re.match(r"^([A-Z0-9-]+)_2018_f36_(MLLW|NAVD)\.csv$", name)
        if not m:
            continue
        st, datum = m.groups()
        head, rows = read_csv(os.path.join(d, name))
        page = os.path.join(d, f"{st}_2018_f36_MLLW_hc.html" if datum == "MLLW" else f"{st}_2018_f36_hc.html")
        lid = lids.get(st)
        off = offs.get(st)
        if lid in pet and rows and (datum == "MLLW" or off is not None):
            shift = 0.0 if datum == "MLLW" else -off
            t0 = parse_t(rows[0][0])
            try:
                f = petss.forecast(pet[lid], t0, cycle)
            except ValueError as e:
                print(f"  {st}: {e}")
                f = None
            if f is not None:
                # tie P-ETSS to the station's own record (datum and bias): the median gap
                # between Tidewatch's observations and P-ETSS's hourly storm tide over the last day
                mllw_page = os.path.join(d, f"{st}_2018_f36_MLLW_hc.html")
                adj = align(pet[lid], mllw_page, t0) if os.path.exists(mllw_page) else 0.0
                for k in ("astro_tide", "SSforecast", "low", "high"):
                    f[k] = f[k] + adj
                adjs[st] = adj
                if datum == "MLLW":
                    print(f"  {st}: P-ETSS aligned by {adj:+.2f} ft")
            if f is not None:
                f, line, sources[st] = adapt(f, st, guide, pet[lid].get("guidance"))
                out = [[iso(t)] + [fmt(f[k][i] + (shift if k in LEVELS else 0)) for k in F72_KEYS]
                       for i, t in enumerate(f["time"])]
                write_csv(os.path.join(d, name), F72_HEAD, out)
                if os.path.exists(page):
                    petss_page(page, pet[lid], f, shift, st, line)
                done.append(f"{st} {datum}")
                continue
        # no P-ETSS here: Tidewatch's 36-hour forecast under the new field names
        idx = {h: i for i, h in enumerate(head)}
        tw = {"astro_tide": "pa30", "residual": "anom", "SSforecast": "px30"}
        out = [[r[idx["time"]]] + [("%.3f" % float(r[idx[tw[k]]])) if k in tw else "" for k in F72_KEYS]
               for r in rows if r[idx["px30"]] not in ("", "nan")]
        write_csv(os.path.join(d, name), F72_HEAD, out)
        if os.path.exists(page):
            html, series = read_page(page)
            write_page(page, html, rename_series(series), guidance=GUIDANCE["tidewatch"])
    return done, adjs, offs, sources


def align(st_pet, mllw_page, t0):
    _, series = read_page(mllw_page)
    obs = {p[0]: p[1] for s in series if s["name"] == "Observed" for p in s["data"]}
    gaps = [obs[ms(t)] - v for t, v in zip(st_pet["time"], st_pet["TWL"])
            if t.minute == 0 and t0 - timedelta(hours=24) <= t <= t0 and ms(t) in obs and not np.isnan(v)]
    return float(np.median(gaps)) if len(gaps) >= 6 else 0.0


def petss_page(page, st_pet, f, shift, st, line=None):
    """Hindcast: Tidewatch's observations against the P-ETSS tide. Forecast: P-ETSS."""
    html, series = read_page(page)
    obs = next((s for s in series if s["name"] == "Observed"), None)
    if obs is None:
        print(f"  {st}: {os.path.basename(page)} has no observations; chart left as Tidewatch's")
        return
    ot = [datetime.fromtimestamp(p[0] / 1000, timezone.utc) for p in obs["data"]]
    ov = np.array([p[1] for p in obs["data"]], dtype=float)
    tide_h = petss.hindcast_tide(st_pet, ot) + shift + (f["astro_tide"][0] - petss.hindcast_tide(st_pet, [f["time"][0]])[0])
    tt = f["time"]
    new = [
        {"data": obs["data"], "type": "line", "color": "red", "name": "Observed"},
        {"data": pts(ot, tide_h), "type": "line", "color": "blue", "name": "Astronomic Tide"},
        {"data": pts(ot, ov - tide_h), "type": "line", "color": "green", "name": "Residual"},
        {"data": [[ms(t), round(float(lo + shift), 3), round(float(hi + shift), 3)]
                  for t, lo, hi in zip(tt, f["low"], f["high"])],
         "type": "arearange", "name": "Forecast Uncertainty (10%–90%)", "color": CONE, "fillColor": CONE,
         "lineWidth": 0, "zIndex": 0, "marker": {"enabled": False}},
        {"data": pts(tt, f["astro_tide"] + shift), "type": "line", "color": "blue", "name": "Astronomic Tide Forecast"},
        {"data": pts(tt, f["SSforecast"] + shift), "type": "line", "color": "red", "name": "StormSense Forecast",
         "dashStyle": "dash"},
        {"data": pts(tt, f["residual"]), "type": "line", "color": "green", "name": "Residual", "dashStyle": "dash"},
    ]
    write_page(page, html, new, title=f"72 Hour StormSense Forecast for {st}", guidance=line or st_pet.get("guidance", GUIDANCE["petss"]))


# --- hindcasts ---------------------------------------------------------------
def seven_day(raw):
    """Make raw/3d hold 7 days: the 30-day record plus the newer 3-day record,
    trimmed to the 7 days before the latest observation (CSV and charts)."""
    d3, d30 = os.path.join(raw, "3d"), os.path.join(raw, "30d")
    if not (os.path.isdir(d3) and os.path.isdir(d30)):
        return 0
    n = 0
    for name in os.listdir(d3):
        other = os.path.join(d30, name.replace("_3d_", "_30d_"))
        if not os.path.exists(other):
            continue
        if re.match(r"^[A-Z0-9-]+_2018_3d_(MLLW|NAVD)\.csv$", name):
            _, a = read_csv(other)
            head, b = read_csv(os.path.join(d3, name))
            rows = {r[0]: r for r in a}
            rows.update({r[0]: r for r in b})
            if rows:
                last = parse_t(max(rows))
                write_csv(os.path.join(d3, name), head,
                          [rows[k] for k in sorted(rows) if parse_t(k) > last - timedelta(days=7)])
        elif name.endswith("_hc.html"):
            html, s3 = read_page(os.path.join(d3, name))
            _, s30 = read_page(other)
            by = {s["name"]: s for s in s30}
            last = max((p[0] for s in s3 for p in s["data"]), default=0)
            for s in s3:
                first = min((p[0] for p in s["data"]), default=last)
                s["data"] = [p for p in by.get(s["name"], {}).get("data", [])
                             if last - 7 * 86400000 < p[0] < first] + s["data"]
            title = re.search(r'"title": \{"text": "([^"]*)"', html)
            write_page(os.path.join(d3, name), html, s3,
                       title=title.group(1).replace("3 Day", "7 Day") if title else None)
            n += 1
    return n


def hindcasts(raw, tides, offs):
    """7day (raw/3d) and 30day CSVs and charts: observations with the P-ETSS
    astronomic tide and the residual. tides: {ST: {epoch ms: tide, ft above
    Tidewatch's MLLW}}; offs: {ST: Tidewatch MLLW minus NAVD}."""
    n = 0
    for prod in ("3d", "30d"):
        d = os.path.join(raw, prod)
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            m = re.match(r"^([A-Z0-9-]+)_2018_%s_(?:(MLLW|NAVD)\.csv|(MLLW_)?hc\.html|NAVD_hc\.html)$" % prod, name)
            if not m:
                continue
            st = m.group(1)
            navd = "NAVD" in name or (name.endswith("_hc.html") and "_MLLW_" not in name)
            tide = tides.get(st, {})
            shift = 0.0
            if navd:
                shift = -offs[st] if offs.get(st) is not None else None
            if shift is None:
                tide = {}
            path = os.path.join(d, name)
            if name.endswith(".csv"):
                _, rows = read_csv(path)
                out = []
                for r in rows:
                    if len(r) < 2 or r[1] in ("", "nan"):
                        continue
                    v = float(r[1])
                    t = tide.get(ms(parse_t(r[0])))
                    out.append([r[0], fmt(v)] + ([fmt(t + shift), fmt(v - t - shift)]
                                                     if t is not None else ["", ""]))
                write_csv(path, HC_HEAD, out)
            else:
                html, series = read_page(path)
                obs = next((s for s in series if s["name"] == "Observed"), None)
                if obs and tide:
                    tp = [[p[0], round(tide[p[0]] + shift, 3)] for p in obs["data"] if p[0] in tide]
                    rp = [[p[0], round(p[1] - tide[p[0]] - shift, 3)] for p in obs["data"] if p[0] in tide]
                    series = [obs, {"data": tp, "type": "line", "color": "blue", "name": "Astronomic Tide"},
                              {"data": rp, "type": "line", "color": "green", "name": "Residual"}]
                    n += 1
                write_page(path, html, rename_series(series))
    return n
