"""NWS flood categories (Action, Minor, Moderate, Major) for each StormSense
station from the National Water Prediction Service gauge API, in the gauge's
own datum. Standard library only.

    python make_thresholds.py [out.json] [nwps_json_dir]

Stations come from stations_nws.csv (tidewatch_id,nws_lid). With a folder of
saved <LID>.json responses the API is not called. Most coastal Virginia gauges
read in MLLW ("(IN MLLW)" in the name, or MLLW* as the 0 datum); the rest are
read in NAVD88. Categories NWPS leaves unset (-9999) are omitted.
"""
import csv
import json
import os
import sys
import urllib.request

API = "https://api.water.noaa.gov/nwps/v1/gauges/"


def gauge(lid, folder=None):
    if folder:
        return json.load(open(os.path.join(folder, lid + ".json")))
    req = urllib.request.Request(API + lid, headers={"User-Agent": "stormsense-latest (VIMS)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def thresholds(g):
    cats = g["flood"]["categories"]
    vert = {v["abbrev"]: v["value"] for v in ((g.get("datums") or {}).get("vertical") or {}).get("value") or []}
    if "(IN MLLW)" in g["name"].upper() or vert.get("MLLW*") == 0:
        datum = "MLLW"
    elif "NAVD88" in vert:
        datum = "NAVD88"
    else:
        return None
    out = {"lid": g["lid"], "name": g["name"], "datum": datum, "units": g["flood"]["stageUnits"]}
    for k in ("action", "minor", "moderate", "major"):
        v = (cats.get(k) or {}).get("stage")
        if v is not None and v > -999:
            out[k] = v
    return out if len(out) > 4 else None


def main(out="thresholds.json", folder=None):
    here = os.path.dirname(os.path.abspath(__file__))
    table, failed = {}, []
    for row in csv.DictReader(open(os.path.join(here, "stations_nws.csv"))):
        try:
            t = thresholds(gauge(row["nws_lid"], folder))
        except Exception as e:
            failed.append("%s %s: %s" % (row["tidewatch_id"], row["nws_lid"], e))
            continue
        if t:
            table[row["tidewatch_id"]] = t
    if not table:
        sys.exit("no thresholds read: " + "; ".join(failed))
    with open(out, "w") as f:
        json.dump(table, f, indent=1, sort_keys=True)
    print("%d stations with flood thresholds; %d failed" % (len(table), len(failed)))
    for x in failed:
        print("  failed:", x)


if __name__ == "__main__":
    main(*sys.argv[1:])
