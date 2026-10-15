"""Write the StormSense CSV/JSON metadata documents: one PDF and one JSON per
product (fore72, 7day, 30day) and datum (MLLW, NAVD88), into metadata/.

    python tools/make_metadata.py SAMPLES_DIR [OUT_DIR]

SAMPLES_DIR holds the example chart screenshots (fore72_MLLW.png, fore72_NAVD.png,
7day_MLLW.png, ...) and the matching example CSVs (fore72_MLLW.csv, ...) taken
from the live site. The PDF is rendered from HTML with Playwright (node), in
Arial throughout.
"""
import base64
import csv
import json
import os
import subprocess
import sys

VDATUM = "https://vdatum.noaa.gov/vdatumweb/"
NWPS = "https://water.noaa.gov/"
SITE = "NOAA&rsquo;s Sewells Point tide gauge, in Norfolk, VA"
ISSUE = "October 15, 2026 at 16:36 EDT (2026-10-15T20:36:00Z)"
CONE_RGBA = "rgba(20,38,96,0.5)"
DATUM_NAME = {"MLLW": "Mean Lower Low Water (MLLW)", "NAVD": "the North American Vertical Datum of 1988 (NAVD88)"}
FT = "Formatted in units of feet rounded to three decimal places (thousandth of a foot)"
DT = ("Date and time in Zulu/GMT (UTC), formatted as a string leading with the date as &ldquo;YYYY-MM-DD&rdquo; "
      "followed by the time (T) as &ldquo;hh:mm:ss&rdquo; and Z for Zulu time. Recorded in regular 6-minute "
      "intervals (0, 6, 12 &hellip; 54 minutes past the hour), listed in chronological order (Table 1, first column).")

# chart series as drawn in Figure 1: (legend label, color, dashed, marker)
SERIES = {
    "obs": ("Observed", "#ff0000", False, "circle"),
    "tide": ("Astronomic Tide", "#0000ff", False, "diamond"),
    "res": ("Residual", "#00E5EE", False, "square"),
    "tidef": ("Astronomic Tide Forecast", "#0000ff", False, "triangle"),
    "ssf": ("StormSense Forecast", "#ff0000", True, "circle"),
    "resf": ("Residual", "#00E5EE", True, "diamond"),
    "cone": ("Forecast Uncertainty (10%&ndash;90%)", CONE_RGBA, False, "cone"),
}

DATUMS = [  # MLLW charts: (label, color, line style, definition)
    ("HAT+1 &hellip; HAT+4", "#b0b0b0", "dot", "Reference lines 1, 2, 3 and 4 feet above HAT, for reading how far an extreme water level rises above the highest predicted tide. Where a station has no published HAT, the steps start from MHHW."),
    ("HAT", "#8a8a8a", "dash", "Highest Astronomical Tide: the highest water level predicted from the tide alone (no weather) over the National Tidal Datum Epoch (NTDE, 1983&ndash;2001)."),
    ("MHHW", "#8a8a8a", "short", "Mean Higher High Water: the average of the higher of each day&rsquo;s two high tides over the NTDE; a common threshold for nuisance (high-tide) flooding."),
    ("NAVD88", "#555555", "solid", "North American Vertical Datum of 1988: the fixed, land-based geodetic datum used for surveyed elevations, roads and flood maps."),
    ("MSL", "#8a8a8a", "dash", "Mean Sea Level: the average of hourly water levels over the NTDE."),
    ("MLLW", "#555555", "solid", "Mean Lower Low Water: the average of the lower of each day&rsquo;s two low tides over the NTDE. It is zero on these charts and in these downloads."),
    ("LAT", "#8a8a8a", "dash", "Lowest Astronomical Tide: the lowest water level predicted from the tide alone over the NTDE."),
]
THRESHOLDS = [  # NAVD88 charts: (label, line color, label color, definition)
    ("Action (yellow)", "#FFFF00", "#a39700", "The level at which the NWS and its partners begin preparing for possible flooding; water may reach the edges of low-lying areas, but significant impacts are not yet expected."),
    ("Minor (orange)", "#FF9900", "#FF9900", "Minor flooding: minimal or no property damage, but possibly some public threat, such as water over low-lying roads, parking lots and parks near the shore."),
    ("Moderate (red)", "#FF0000", "#FF0000", "Moderate flooding: some inundation of structures and roads near the water, with some evacuations of people or moving of property to higher ground."),
    ("Major (purple)", "#CC33FF", "#CC33FF", "Major flooding: extensive inundation of structures and roads, with significant evacuations of people and transfer of property to higher elevations."),
]
MLLW_DEF = ("Mean Lower Low Water: the average of the lower of each day&rsquo;s two low tides over the National Tidal "
            "Datum Epoch (1983&ndash;2001). The gray MLLW line in Figure 1 marks where the MLLW zero (the chart datum "
            "used on nautical charts and in tide tables) sits on the NAVD88 scale, labeled with its NAVD88 elevation.")
NWS_TEXT = ("The flood categories on NAVD88 charts (colored lines labeled at the right of Figure 1) are defined by "
            "the National Weather Service (NWS), not by StormSense. NWS forecast offices set them for each forecast "
            "gauge together with local emergency managers, based on the impacts observed near that gauge, and publish "
            "them through the National Water Prediction Service. StormSense refreshes them from NWPS with every update "
            "and shows them only at stations tied to an NWS gauge; thresholds that NWS publishes in MLLW are shifted "
            "to NAVD88 with the station&rsquo;s MLLW&ndash;NAVD88 separation.")
SOURCE_MLLW = ("At NOAA-operated tide gauges the datums are NOAA&rsquo;s published tidal datums for that station. USGS, "
               "VDEM and StormSense sensors natively report live water levels in NAVD88 only, so their MLLW forecasts "
               "and observations are datum-shifted from NAVD88 using the MLLW&ndash;NAVD88 separation derived from "
               "NOAA VDatum, and their tidal datum lines come from VDatum as well. Not every datum is available at "
               "every station.")
SOURCE_NAVD = ("For most NOAA-operated tide gauges the MLLW&ndash;NAVD88 separation is NOAA&rsquo;s published value for "
               "that station. USGS, VDEM and StormSense sensors natively report live water levels in NAVD88 only, so "
               "their MLLW translation datum is derived from NOAA VDatum.")
OLD = {"date_time": "date_time_z", "astro_tide": "astro_tide_ft", "surge": "surge_ft", "bias": "bias_ft",
       "residual": "residual_ft", "SSforecast": "SSforecast_ft", "SSforecast_p10": "SSforecast_p10_ft",
       "SSforecast_p90": "SSforecast_p90_ft", "surge_p10": "surge_p10_ft", "surge_p90": "surge_p90_ft"}


def fields(prod, dat):
    """[(name, units, series key or None, description)] for one product and datum."""
    rel = f"{FT} relative to {DATUM_NAME[dat]}."
    if prod == "fore72":
        return [
            ("date_time_z", "UTC", None, DT),
            ("astro_tide_ft", "ft", "tidef", f"Harmonically predicted astronomical tide for the next 72 hours from the NWS P-ETSS model (solid blue line in the forecast period of Figure 1). {rel}"),
            ("surge_ft", "ft", None, "Ensemble-mean storm surge from P-ETSS (the Probabilistic Extra-Tropical Storm Surge model of the NWS Meteorological Development Laboratory, run with an ensemble of weather forecasts): the water level change driven by forecast wind and air pressure. Hourly guidance interpolated to 6 minutes and smoothed with a 3-hour low-pass filter. Feet; a height difference, so the same in MLLW and NAVD88."),
            ("bias_ft", "ft", None, "The observation-based correction P-ETSS adds to its surge, from the recent difference between the gauge&rsquo;s observations and the modeled tide plus surge; it is held or decays through the forecast, and is 0.000 where P-ETSS applies no correction. Feet; the same in MLLW and NAVD88."),
            ("residual_ft", "ft", "resf", "Forecast residual: the non-tidal part of the forecast, SSforecast_ft &minus; astro_tide_ft (surge_ft + bias_ft), drawn as the dashed cyan line in Figure 1. Feet; the same in MLLW and NAVD88."),
            ("SSforecast_ft", "ft", "ssf", f"The StormSense 72-hour storm tide forecast, the ensemble-mean total water level: astro_tide_ft + surge_ft + bias_ft (dashed red line in Figure 1). {rel}"),
            ("SSforecast_p10_ft", "ft", "cone", f"10th percentile of the ensemble total water level (P-ETSS&rsquo;s 90% exceedance level): the lower edge of the shaded cone of uncertainty in Figure 1. {rel}"),
            ("SSforecast_p90_ft", "ft", None, f"Upper edge of the cone in Figure 1: the 90th percentile of the ensemble total water level (P-ETSS&rsquo;s 10% exceedance level). Nine in ten ensemble members fall at or below it. {rel}"),
            ("surge_p10_ft, surge_p90_ft", "ft", None, "10th and 90th percentiles of the ensemble storm surge (P-ETSS 90% and 10% exceedance). Feet; the same in MLLW and NAVD88."),
        ]
    span = "7 days (168 hours)" if prod == "7day" else "30 days"
    return [
        ("date_time_z", "UTC", None, DT),
        ("water_level_ft", "ft", "obs", f"Observed storm tide water level for the past {span} at this monitoring location (solid red line in Figure 1). {rel}"),
        ("astro_tide_ft", "ft", "tide", f"Harmonically predicted astronomical tide at the same times (solid blue line in Figure 1), from P-ETSS, with NOAA CO-OPS tide predictions further back at NOAA gauges (they match P-ETSS&rsquo;s tide to 0.01 ft). Blank in the CSV (null in the JSON) where no prediction reaches back that far. {rel}"),
        ("residual_ft", "ft", "res", "Observed residual: water_level_ft &minus; astro_tide_ft, the non-tidal water level from wind, air pressure, rain and river flow (solid cyan line in Figure 1). Feet; the same in MLLW and NAVD88. Blank (null) where astro_tide_ft is blank."),
    ]


FORE72_NOTE = ("P-ETSS levels are tied to each gauge&rsquo;s own record: the median difference between the observations "
               "and P-ETSS over the 24 hours before the forecast starts is added to astro_tide_ft, SSforecast_ft and its "
               "percentiles (0.00 ft at most NOAA gauges). At stations without a P-ETSS point, the files keep the same "
               "fields with the 36-hour forecast in astro_tide_ft, residual_ft and SSforecast_ft and the P-ETSS-only "
               "fields left blank (null in the JSON).")
JSON_NOTE = ("Each CSV has a JSON twin at the same address with .json in place of .csv: station, product, datum, units, "
             "time_zone, updated, source, fields and a link to this metadata, then a data list with one record per CSV "
             "row keyed by the field names above (numbers in feet, blanks as null).")


def describe(prod, dat):
    """Everything both the PDF and the JSON say for one product and datum."""
    label = {"fore72": "72-Hour Forecasts (fore72)", "7day": "7-Day Hindcasts (7day)", "30day": "30-Day Hindcasts (30day)"}[prod]
    if prod == "fore72":
        fig = f"Example StormSense Chart of 72-hour forecast data ({dat}) at {SITE}, issued {ISSUE} from the P-ETSS 12Z cycle. The red-shaded period is the observed hindcast leading up to the forecast; the blue-shaded period is the 72-hour forecast."
        tab = f"Example StormSense Table of the first rows of 72-hour forecast data ({dat}) at {SITE}, issued {ISSUE}."
        scope = "fore72 downloads only include data series for the 72-hour forecast period (the dashed lines and shaded cone in the blue-shaded period of Figure 1; sample rows in Table 1)"
        intro = ("Figure 1 shows a StormSense 72-hour forecast chart and Table 1 the first rows of the matching download. "
                 "Each field below is tied to the series it is drawn as in Figure 1 and to its column in Table 1.")
    else:
        span = "7 days (168 hours)" if prod == "7day" else "30 days"
        fig = f"Example StormSense Chart of {span.split(' (')[0]} of hindcast data ({dat}) at {SITE}, looking backward {span} from {ISSUE}."
        tab = f"Example StormSense Table of {prod} hindcast data ({dat}) at {SITE}, through {ISSUE}: the first and last rows, with the rows between skipped (&hellip;)."
        scope = f"{prod} downloads only include observations from the last {span} hindcast period (Figure 1; sample rows in Table 1)"
        intro = (f"Figure 1 shows a StormSense {prod} hindcast chart and Table 1 the first and last rows of the matching download. "
                 "Each field below is tied to the series it is drawn as in Figure 1 and to its column in Table 1.")
    d = {"title": f"Metadata: StormSense Comma Separated Values (CSV) and JavaScript Object Notation (JSON) for {label}", "product": prod,
         "datum": "MLLW" if dat == "MLLW" else "NAVD88", "units": "feet", "time_zone": "UTC (Z)",
         "interval_minutes": 6, "introduction": intro, "figure_1": fig, "table_1": tab, "fields_scope": scope,
         "fields": [{"name": n, "units": u, "chart_series": SERIES[s][0] if s else None, "description": t}
                    for n, u, s, t in fields(prod, dat)],
         "notes": ([FORE72_NOTE] if prod == "fore72" else []) + [JSON_NOTE]}
    if dat == "MLLW":
        d["datums"] = {"description": "Gray reference lines labeled at the right of Figure 1; click a label to hide or show its line.",
                       "lines": [{"name": n, "definition": t} for n, _, _, t in DATUMS],
                       "source": SOURCE_MLLW, "vdatum": VDATUM}
    else:
        d["nws_flood_thresholds"] = {"description": NWS_TEXT, "source": NWPS,
                                     "thresholds": [{"name": n, "color": c, "definition": t} for n, c, _, t in THRESHOLDS]}
        d["mllw_translation_datum"] = {"definition": MLLW_DEF, "source": SOURCE_NAVD, "vdatum": VDATUM}
    return d


# --- PDF -------------------------------------------------------------------------------------------

def plain(s):
    """HTML entities -> text for the JSON."""
    import html
    return html.unescape(s)


def icon(key):
    label, color, dash, marker = SERIES[key]
    if marker == "cone":
        g = f'<rect x="2" y="3" width="26" height="10" rx="3" fill="{color}"/>'
    else:
        m = {"circle": f'<circle cx="15" cy="8" r="4" fill="{color}"/>',
             "diamond": f'<path d="M15 3 L20 8 L15 13 L10 8 Z" fill="{color}"/>',
             "square": f'<rect x="11" y="4" width="8" height="8" fill="{color}"/>',
             "triangle": f'<path d="M10 4 L20 4 L15 12 Z" fill="{color}"/>'}[marker]
        da = ' stroke-dasharray="5,3"' if dash else ""
        g = f'<line x1="1" y1="8" x2="29" y2="8" stroke="{color}" stroke-width="2.5"{da}/>{m}'
    return f'(<span class="ic"><svg width="30" height="16" viewBox="0 0 30 16">{g}</svg>{label}</span>) '


def line(color, label, style="solid", text=None, width=1.6):
    da = {"solid": "", "dash": ' stroke-dasharray="7,4"', "short": ' stroke-dasharray="4,3"', "dot": ' stroke-dasharray="1.5,3"'}[style]
    return (f'<span class="ic"><svg width="30" height="16"><line x1="1" y1="8" x2="29" y2="8" stroke="{color}" '
            f'stroke-width="{width}"{da}/></svg><b style="color:{text or color}">{label}</b></span>')


def fld(name, text):
    return f'<div class="f"><div class="fn">{name}</div><div class="fd">{text}</div></div>'


def table(path, head_rows, tail_rows):
    with open(path) as f:
        rows = list(csv.reader(f))
    head, body = [OLD.get(h, h) for h in rows[0]], rows[1:]
    sel = body[:head_rows] + ([["&hellip;"] * len(head)] + body[-tail_rows:] if tail_rows else [])
    th = "".join(f"<th>{h}</th>" for h in head)
    tr = "".join("<tr>" + "".join(f"<td>{'0.000' if v == '-0.000' else v}</td>" for v in r) + "</tr>" for r in sel)
    return f'<table class="data"><tr>{th}</tr>{tr}</table>'


CSS = """
@page{size:letter;margin:0.55in 0.65in}
*{font-family:Arial,'Liberation Sans',Helvetica,sans-serif}
body{font-size:10pt;color:#111;line-height:1.28}
h1{font-size:13pt;margin:0 0 8px;text-decoration:underline;text-align:center}
h2{font-size:11pt;margin:12px 0 5px;break-after:avoid}
h2+p,h2+.f{break-before:avoid}
.sub{font-weight:normal;font-style:italic;font-size:9pt}
img.chart{width:100%;border:1px solid #ccc}
.cap{font-style:italic;margin:5px 0 8px}
.f{display:flex;margin:3px 0 6px;break-inside:avoid}
.fn{flex:0 0 140px;font-weight:bold}
.fd{flex:1}
.ic{display:inline-flex;align-items:center;gap:3px;font-weight:bold;white-space:nowrap}
.ic svg{flex:none}
.note{font-size:9.4pt}
table.data{border-collapse:collapse;margin:4px auto;font-size:7.8pt;white-space:nowrap}
table.data td,table.data th{border:1px solid #444;padding:1px 5px;text-align:left}
table.data th{background:#eef3f8}
a{color:#0d5fa8}
"""


def render_html(d, prod, dat, shot, sample, rows):
    fl = "".join(fld(f["name"], (icon(s) if s else "") + t) for f, (_, _, s, t) in zip(d["fields"], fields(prod, dat)))
    notes = "".join(f'<p class="note">{n}</p>' for n in d["notes"])
    vd = f'<a href="{VDATUM}">NOAA VDatum</a> (<a href="{VDATUM}">{VDATUM}</a>)'
    if dat == "MLLW":
        body = "".join(fld(line(c, n, st), t) for n, c, st, t in DATUMS)
        extra = (f'<h2>Datums <span class="sub">({d["datums"]["description"]})</span></h2>{body}'
                 f'<p class="note">Datum source: {SOURCE_MLLW.replace("NOAA VDatum", vd)}</p>')
    else:
        body = "".join(fld(line(c, n, text=tc, width=3), t) for n, c, tc, t in THRESHOLDS)
        nws = NWS_TEXT.replace("National Water Prediction Service", f'<a href="{NWPS}">National Water Prediction Service</a>')
        extra = (f'<h2>NWS Flood Thresholds</h2><p>{nws}</p>{body}<h2>MLLW translation datum</h2>'
                 f'{fld(line("#555555", "MLLW"), MLLW_DEF)}<p class="note">Datum source: {SOURCE_NAVD.replace("NOAA VDatum", vd)}</p>')
    with open(shot, "rb") as f:
        src = "data:image/png;base64," + base64.b64encode(f.read()).decode()
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{CSS}</style></head><body>
<h1>{d["title"].replace("(CSV) ", "(CSV)<br>")}</h1>
<img class="chart" src="{src}">
<p class="cap"><b>Figure 1.</b> {d["figure_1"]}</p>
<p>{d["introduction"]}</p>
<h2>Fields <span class="sub">*{d["fields_scope"]}*</span></h2>
{fl}
<div style="break-inside:avoid"><p class="cap" style="margin-top:10px"><b>Table 1.</b> {d["table_1"]}</p>
{table(sample, *rows)}</div>
{notes}
{extra}
</body></html>"""


def main(samples, out):
    os.makedirs(out, exist_ok=True)
    pages = []
    rows = {"fore72": (8, 0), "7day": (3, 2), "30day": (3, 2)}
    for dat in ("MLLW", "NAVD"):
        for prod in ("fore72", "7day", "30day"):
            name = f"stormsense-metadata-for-{prod}-csv-data{'-NAVD' if dat == 'NAVD' else ''}"
            d = describe(prod, dat)
            html_path = os.path.join(out, name + ".html")
            with open(html_path, "w") as f:
                f.write(render_html(d, prod, dat, os.path.join(samples, f"{prod}_{dat}.png"),
                                    os.path.join(samples, f"{prod}_{dat}.csv"), rows[prod]))
            pages.append(html_path)
            d["companion_pdf"] = name + ".pdf"  # holds Figure 1 and Table 1
            with open(os.path.join(out, name + ".json"), "w") as f:
                json.dump(json.loads(plain(json.dumps(d))), f, indent=1, ensure_ascii=False)
    js = ("const {chromium}=require('playwright');(async()=>{const b=await chromium.launch();const p=await b.newPage();"
          "for(const f of process.argv.slice(1)){await p.goto('file://'+f);await p.waitForTimeout(300);"
          "await p.pdf({path:f.replace(/\\.html$/,'.pdf'),format:'Letter',printBackground:true,preferCSSPageSize:true});}"
          "await b.close();})();")
    subprocess.run(["node", "-e", js] + [os.path.abspath(p) for p in pages], check=True)
    for p in pages:
        os.remove(p)
        print(p[:-5] + ".pdf")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(__file__), "..", "metadata"))
