"""Turn the Tidewatch placeholder files into StormSense products, in place in
the raw Tidewatch folders (publish.py renames them afterwards):

  fore72  P-ETSS 72-hour forecast (6-minute, with a 10-90% uncertainty cone)
          wherever P-ETSS covers the station's NWS gauge; elsewhere Tidewatch's
          36-hour forecast. CSV fields date_time, astro_tide, residual,
          SSforecast, SSforecast_p10, SSforecast_p90.
  7day    the last 7 days, from the 30-day hindcast plus the newer 3-day one.
  30day   the 30-day hindcast.
  Hindcast CSV fields: date_time, water_level_ft.
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
F72_HEAD = ["date_time", "astro_tide", "surge", "bias", "residual", "SSforecast", "SSforecast_p10",
            "SSforecast_p90", "surge_p10", "surge_p90"]
LEVELS = {"astro_tide", "SSforecast", "low", "high"}  # water levels (move with the datum)
RENAME = {"Astronomic (m30)": "Astronomic Tide", "Astronomic (m30) Forecast": "Astronomic Tide Forecast",
          "36hr Forecast": "StormSense Forecast"}


# --- Highcharts pages --------------------------------------------------------
def read_page(path):
    html = open(path, encoding="utf-8").read()
    m = DATA.search(html)
    js = UTC.sub(lambda u: str(int(datetime(int(u[1]), int(u[2]) + 1, int(u[3]), int(u[4]), int(u[5]), int(u[6]),
                                            tzinfo=timezone.utc).timestamp() * 1000)), m.group(1))
    return html, json.loads(js)


def write_page(path, html, series, title=None):
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
def fore72(raw, lids, pet, cycle):
    """Rewrite raw/f36 pages and CSVs. lids: {ST: NWS id}; pet: {NWS id: P-ETSS station}."""
    d = os.path.join(raw, "f36")
    done, adjs = [], {}
    offs = {n.split("_")[0]: offset(d, n.split("_")[0]) for n in os.listdir(d) if n.endswith("_f36_NAVD.csv")}
    for name in sorted(os.listdir(d)):
        m = re.match(r"^([A-Z0-9]+)_2018_f36_(MLLW|NAVD)\.csv$", name)
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
                out = [[iso(t)] + [fmt(f[k][i] + (shift if k in LEVELS else 0)) for k in F72_KEYS]
                       for i, t in enumerate(f["time"])]
                write_csv(os.path.join(d, name), F72_HEAD, out)
                if os.path.exists(page):
                    petss_page(page, pet[lid], f, shift, st)
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
            write_page(page, html, rename_series(series))
    return done, adjs, offs


def align(st_pet, mllw_page, t0):
    _, series = read_page(mllw_page)
    obs = {p[0]: p[1] for s in series if s["name"] == "Observed" for p in s["data"]}
    gaps = [obs[ms(t)] - v for t, v in zip(st_pet["time"], st_pet["TWL"])
            if t.minute == 0 and t0 - timedelta(hours=24) <= t <= t0 and ms(t) in obs and not np.isnan(v)]
    return float(np.median(gaps)) if len(gaps) >= 6 else 0.0


def petss_page(page, st_pet, f, shift, st):
    """Hindcast: Tidewatch's observations against the P-ETSS tide. Forecast: P-ETSS."""
    html, series = read_page(page)
    obs = next(s for s in series if s["name"] == "Observed")
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
    write_page(page, html, new, title=f"72 Hour StormSense Forecast for {st}")


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
        if re.match(r"^[A-Z0-9]+_2018_3d_(MLLW|NAVD)\.csv$", name):
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
            m = re.match(r"^([A-Z0-9]+)_2018_%s_(?:(MLLW|NAVD)\.csv|(MLLW_)?hc\.html|NAVD_hc\.html)$" % prod, name)
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
                    out.append([r[0], "%.3f" % v] + (["%.3f" % (t + shift), "%.3f" % (v - t - shift)]
                                                     if t is not None else ["", ""]))
                write_csv(path, ["date_time", "water_level_ft", "astro_tide", "residual"], out)
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
