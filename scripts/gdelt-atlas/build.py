#!/usr/bin/env python3
"""
GDELT Atlas builder — precomputes a self-contained dark-mode world map + news
feed artifact (atlas.html) from real GDELT story data.

Pipeline:
  1. Load Natural Earth 110m country geometry (name + ISO3), project to
     equirectangular, simplify -> embedded path data (no map lib at runtime).
  2. Load the fetched stories snapshot (--stories path). Since 2026-10-10 the
     source is the KEYLESS bulk route (fetch_bulk_stories.py, GDELT's published
     15-minute event exports); fetch_stories.py's GDELT Cloud path is dead from
     this host (the free plan 403s, which froze the atlas at 2026-10-02).
  3. Aggregate per country: story count, max derived salience, category mix,
     top stories. Embed the feed + per-country stats as JSON into atlas.html.

Output: single HTML file, no network, no dependencies. Dark mode Monitor
surface. Countries with no coverage render dim; nothing is fabricated.

Usage:
  python3 build.py [--stories /tmp/gdelt_stories_big.json] [--out atlas.html]
"""
import argparse
import json
import math
import os

ROOT = os.path.dirname(os.path.abspath(__file__))

# ---- world geometry -------------------------------------------------------

def project_ring(ring, width=1000):
    """Equirectangular projection: lon/lat -> x/y in [0,width] x [0,width/2]."""
    height = width / 2
    pts = []
    for lon, lat in ring:
        x = (lon + 180.0) / 360.0 * width
        y = (90.0 - lat) / 180.0 * height
        pts.append(f"{x:.1f},{y:.1f}")
    return " ".join(pts)


def polygon_to_path(geom):
    """GeoJSON Polygon/MultiPolygon -> SVG path d string."""
    if geom["type"] == "Polygon":
        polys = [geom["coordinates"]]
    else:
        polys = geom["coordinates"]
    parts = []
    for poly in polys:
        outer = poly[0]
        d = f"M {project_ring(outer)} Z"
        # holes as counter-rings
        for hole in poly[1:]:
            d += f" M {project_ring(hole)} Z"
        parts.append(d)
    return " ".join(parts)


def load_world(path):
    with open(path) as f:
        gj = json.load(f)
    out = []
    for feat in gj["features"]:
        props = feat.get("properties", {})
        name = props.get("NAME") or props.get("ADMIN") or props.get("name")
        iso3 = (props.get("ISO_A3") or props.get("ADM0_A3") or "").strip()
        # ISO_A3 is "-99" for disputed/contested territories
        if iso3 == "-99" or not iso3:
            iso3 = (props.get("ISO_N3") or "").strip()
        geom = feat.get("geometry")
        if not geom:
            continue
        out.append({
            "name": name,
            "iso3": iso3,
            "d": polygon_to_path(geom),
        })
    return out


# ---- story aggregation ----------------------------------------------------

ISO_ALIASES = {
    "United States": "USA", "United States of America": "USA", "USA": "USA",
    "China": "CHN", "Russia": "RUS", "Ukraine": "UKR", "Israel": "ISR",
    "Iran": "IRN", "North Korea": "PRK", "Pakistan": "PAK", "India": "IND",
    "Brazil": "BRA", "Germany": "DEU", "France": "FRA", "United Kingdom": "GBR",
    "UK": "GBR", "Taiwan": "TWN", "Saudi Arabia": "SAU", "Turkey": "TUR",
    "Mexico": "MEX", "Nigeria": "NGA", "South Korea": "KOR", "Japan": "JPN",
    "Canada": "CAN", "Australia": "AUS", "Italy": "ITA", "Spain": "ESP",
    "Poland": "POL", "Netherlands": "NLD", "Sweden": "SWE", "Norway": "NOR",
    "Finland": "FIN", "Denmark": "DNK", "Belgium": "BEL", "Switzerland": "CHE",
    "Austria": "AUT", "Ireland": "IRL", "Portugal": "PRT", "Greece": "GRC",
    "Czechia": "CZE", "Czech Republic": "CZE", "Hungary": "HUN", "Romania": "ROU",
    "Bulgaria": "BGR", "Serbia": "SRB", "Croatia": "HRV", "Albania": "ALB",
    "Lithuania": "LTU", "Latvia": "LVA", "Estonia": "EST", "Slovakia": "SVK",
    "Slovenia": "SVN", "Luxembourg": "LUX", "Malta": "MLT", "Cyprus": "CYP",
    "Iceland": "ISL", "Belarus": "BLR", "Moldova": "MDA", "Georgia": "GEO",
    "Armenia": "ARM", "Azerbaijan": "AZE", "Kazakhstan": "KAZ", "Uzbekistan": "UZB",
    "Turkmenistan": "TKM", "Kyrgyzstan": "KGZ", "Tajikistan": "TJK",
    "Afghanistan": "AFG", "Bangladesh": "BGD", "Sri Lanka": "LKA",
    "Nepal": "NPL", "Bhutan": "BTN", "Myanmar": "MMR", "Thailand": "THA",
    "Vietnam": "VNM", "Cambodia": "KHM", "Laos": "LAO", "Malaysia": "MYS",
    "Singapore": "SGP", "Indonesia": "IDN", "Philippines": "PHL",
    "Mongolia": "MNG", "New Zealand": "NZL", "Fiji": "FJI",
    "Egypt": "EGY", "Libya": "LBY", "Tunisia": "TUN", "Algeria": "DZA",
    "Morocco": "MAR", "Sudan": "SDN", "South Sudan": "SSD", "Ethiopia": "ETH",
    "Kenya": "KEN", "Uganda": "UGA", "Tanzania": "TZA", "Somalia": "SOM",
    "DR Congo": "COD", "Democratic Republic of the Congo": "COD",
    "Congo": "COG", "Republic of Congo": "COG", "Ghana": "GHA",
    "Ivory Coast": "CIV", "Côte d'Ivoire": "CIV", "Senegal": "SEN",
    "Mali": "MLI", "Niger": "NER", "Burkina Faso": "BFA", "Chad": "TCD",
    "Cameroon": "CMR", "Angola": "AGO", "Mozambique": "MOZ", "Zambia": "ZMB",
    "Zimbabwe": "ZWE", "Botswana": "BWA", "Namibia": "NAM", "South Africa": "ZAF",
    "Madagascar": "MDG", "Rwanda": "RWA", "Burundi": "BDI",
    "Argentina": "ARG", "Chile": "CHL", "Peru": "PER", "Colombia": "COL",
    "Venezuela": "VEN", "Ecuador": "ECU", "Bolivia": "BOL", "Paraguay": "PRY",
    "Uruguay": "URY", "Guyana": "GUY", "Suriname": "SUR", "Panama": "PAN",
    "Costa Rica": "CRI", "Nicaragua": "NIC", "Honduras": "HND",
    "Guatemala": "GTM", "El Salvador": "SLV", "Belize": "BLZ", "Cuba": "CUB",
    "Haiti": "HTI", "Dominican Republic": "DOM", "Jamaica": "JAM",
    "Trinidad and Tobago": "TTO", "Puerto Rico": "PRI",
    "United Arab Emirates": "ARE", "UAE": "ARE", "Qatar": "QAT",
    "Kuwait": "KWT", "Bahrain": "BHR", "Oman": "OMN", "Yemen": "YEM",
    "Jordan": "JOR", "Lebanon": "LBN", "Syria": "SYR", "Iraq": "IRQ",
    "Palestine": "PSE", "West Bank": "PSE", "Gaza": "PSE",
}


def clean_country(raw):
    if not raw:
        return None
    s = str(raw).strip()
    if not s:
        return None
    # direct ISO3
    if len(s) == 3 and s.isalpha():
        return s.upper()
    return ISO_ALIASES.get(s)


def aggregate_stories(stories):
    """Return {iso3: {...country stats...}} and a global feed list."""
    by_country = {}
    feed = []
    for s in stories:
        geo = s.get("geo") or {}
        country = clean_country(geo.get("country"))
        metrics = s.get("metrics") or {}
        sig = metrics.get("significance") or 0
        cat = s.get("category") or s.get("category_code") or "Uncategorized"
        rec = {
            "id": s.get("id", ""),
            "title": s.get("title", ""),
            "url": s.get("url", ""),
            "date": s.get("story_date", ""),
            "category": cat,
            "significance": round(sig, 4),
            "articles": metrics.get("article_count", 0),
            "country": geo.get("country") or "",
            "iso3": country or "",
            "subcategory": s.get("subcategory") or "",
            "top_articles": [a.get("url") for a in (s.get("top_articles") or [])],
        }
        feed.append(rec)
        if not country:
            continue
        c = by_country.setdefault(country, {
            "iso3": country, "count": 0, "sig_sum": 0.0,
            "cats": {}, "stories": [],
        })
        c["count"] += 1
        c["sig_sum"] += sig
        c["cats"][cat] = c["cats"].get(cat, 0) + 1
        c["stories"].append(rec)

    out = {}
    for iso3, c in by_country.items():
        top_cat = max(c["cats"].items(), key=lambda kv: kv[1])[0]
        c["avg_sig"] = round(c["sig_sum"] / c["count"], 4)
        c["max_sig"] = round(max(s["significance"] for s in c["stories"]), 4)
        c["top_cat"] = top_cat
        c["top_stories"] = sorted(c["stories"], key=lambda s: -s["significance"])[:5]
        # The per-country story list is embedded data the JS never reads (the panel renders
        # stats.top_stories only); dropping it keeps the census for the stats while cutting the
        # payload from ~8 MB to <1 MB with a full 3-day corpus.
        c.pop("stories", None)
        c.pop("sig_sum", None)
        out[iso3] = c
    return out, feed


# ---- build -----------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stories", default="/tmp/gdelt_stories_big.json")
    ap.add_argument("--out", default=os.path.join(ROOT, "atlas.html"))
    args = ap.parse_args()

    world = load_world(os.path.join(ROOT, "ne110.geojson"))
    print(f"world countries: {len(world)}")

    with open(args.stories) as f:
        stories = json.load(f)
    print(f"stories loaded: {len(stories)}")

    by_country, feed = aggregate_stories(stories)
    print(f"countries with coverage: {len(by_country)} | feed items: {len(feed)}")

    # Attach per-country stats onto world features (by iso3)
    for c in world:
        stats = by_country.get(c["iso3"])
        c["stats"] = stats or None

    snapshot = {
        "generated": __import__("datetime").datetime.now(timezone := __import__("datetime").timezone.utc).isoformat(),
        "countries": world,
        "feed": sorted(feed, key=lambda r: (-r["significance"], r["date"]))[:400],
        "total_stories": len(feed),
        "covered": len(by_country),
    }

    html = TEMPLATE.replace("__SNAPSHOT__", json.dumps(snapshot, ensure_ascii=False))
    with open(args.out, "w") as f:
        f.write(html)
    size_kb = os.path.getsize(args.out) / 1024
    print(f"wrote {args.out} ({size_kb:.0f} KB)")


TEMPLATE = r"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>GDELT Atlas — Global News Signal Map</title>
<style>
/* ---------- tokens ---------- */
:root {
  --bg: #0a0c10;
  --bg-2: #0f1218;
  --panel: #11151d;
  --panel-2: #161b25;
  --line: #1e2430;
  --line-2: #2a3242;
  --ink: #e6e9ef;
  --ink-2: #9aa3b2;
  --ink-3: #5c6572;
  --accent: #e8a33d;          /* amber — alert/posture accent */
  --accent-2: #4dc3a2;        /* teal — calm/positive */
  --danger: #e05d5d;
  --mono: "SF Mono", ui-monospace, "Cascadia Code", Menlo, monospace;
  --sans: "Avenir Next", "Segoe UI", system-ui, -apple-system, sans-serif;
  --r: 8px;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { height: 100%; }
body {
  background: var(--bg);
  color: var(--ink);
  font-family: var(--sans);
  font-size: 14px;
  line-height: 1.45;
  overflow: hidden;
}
/* ---------- chrome ---------- */
.topbar {
  display: flex; align-items: center; gap: 16px;
  height: 52px; padding: 0 20px;
  border-bottom: 1px solid var(--line);
  background: var(--bg-2);
  user-select: none;
}
.brand { display: flex; align-items: baseline; gap: 10px; }
.brand .mark { font-family: var(--mono); font-weight: 700; font-size: 15px; letter-spacing: .12em; color: var(--accent); }
.brand .sub { color: var(--ink-3); font-size: 12px; font-family: var(--mono); }
.topbar .spacer { flex: 1; }
.stat { text-align: right; padding: 0 12px; border-left: 1px solid var(--line); }
.stat .k { font-size: 10px; text-transform: uppercase; letter-spacing: .1em; color: var(--ink-3); }
.stat .v { font-family: var(--mono); font-size: 15px; color: var(--ink); }
.live { display: flex; align-items: center; gap: 6px; color: var(--accent-2); font-family: var(--mono); font-size: 12px; }
.live .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--accent-2); }
/* ---------- layout ---------- */
.main { display: grid; grid-template-columns: 1fr 400px; grid-template-rows: minmax(0, 1fr); height: calc(100vh - 52px); }
.map-col { display: flex; flex-direction: column; min-width: 0; min-height: 0; }
.feed-col { border-left: 1px solid var(--line); background: var(--bg-2); display: flex; flex-direction: column; min-width: 0; min-height: 0; }
.map-head { display: flex; align-items: center; gap: 12px; padding: 10px 20px; border-bottom: 1px solid var(--line); }
.map-head h1 { font-size: 14px; font-weight: 600; letter-spacing: .02em; }
.map-title { display: flex; flex-direction: column; gap: 2px; }
.map-head .src { color: var(--ink-3); font-size: 11px; font-family: var(--mono); }
.map-head .src b { color: var(--ink-2); font-weight: 600; }
.map-head .hint { color: var(--ink-3); font-size: 12px; }
.legend { margin-left: auto; display: flex; align-items: center; gap: 6px; font-family: var(--mono); font-size: 11px; color: var(--ink-2); }
.legend .sw { width: 12px; height: 12px; border-radius: 3px; display: inline-block; }
.map-wrap { flex: 1; position: relative; overflow: hidden; }
#worldmap { width: 100%; height: 100%; display: block; }
#worldmap .country { fill: #141a24; stroke: #0a0c10; stroke-width: .5; cursor: pointer; transition: fill .15s ease; }
#worldmap .country:hover { fill: var(--accent); stroke: #fff; }
#worldmap .country.has-data { fill: var(--accent); opacity: .85; }
#worldmap .country.sel { stroke: #fff; stroke-width: 1.4; }
.tooltip {
  position: absolute; pointer-events: none; z-index: 20;
  background: #0d1118ee; border: 1px solid var(--line-2); border-radius: var(--r);
  padding: 10px 12px; font-size: 12px; max-width: 260px;
  box-shadow: 0 8px 24px rgba(0,0,0,.5); backdrop-filter: blur(6px);
  opacity: 0; transition: opacity .12s ease;
}
.tooltip .t-name { font-weight: 600; font-size: 13px; margin-bottom: 4px; }
.tooltip .t-row { color: var(--ink-2); font-family: var(--mono); font-size: 11px; display: flex; justify-content: space-between; gap: 14px; }
.tooltip .t-row b { color: var(--ink); font-weight: 600; }
/* ---------- feed ---------- */
.feed-head { padding: 12px 16px; border-bottom: 1px solid var(--line); }
.feed-head .row1 { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.feed-head h2 { font-size: 13px; font-weight: 600; letter-spacing: .03em; }
.feed-head .count { font-family: var(--mono); font-size: 11px; color: var(--ink-3); }
.cats { display: flex; flex-wrap: wrap; gap: 6px; }
.cat {
  border: 1px solid var(--line-2); background: transparent; color: var(--ink-2);
  font-family: var(--mono); font-size: 10.5px; padding: 3px 9px; border-radius: 20px;
  cursor: pointer; transition: all .12s ease;
}
.cat:hover { border-color: var(--accent); color: var(--ink); }
.cat.on { background: var(--accent); border-color: var(--accent); color: #0a0c10; font-weight: 700; }
.feed-list { flex: 1; overflow-y: auto; padding: 8px 0; }
.feed-list::-webkit-scrollbar { width: 8px; }
.feed-list::-webkit-scrollbar-thumb { background: var(--line-2); border-radius: 4px; }
.story {
  padding: 10px 16px; border-bottom: 1px solid var(--line);
  cursor: pointer; transition: background .1s ease;
}
.story:hover { background: var(--panel); }
.story .s-title { font-size: 13px; color: var(--ink); line-height: 1.4; }
.story .s-meta { display: flex; align-items: center; gap: 8px; margin-top: 6px; flex-wrap: wrap; }
.sig { font-family: var(--mono); font-size: 10.5px; padding: 1px 7px; border-radius: 4px; }
.sig.hi { background: #e05d5d22; color: var(--danger); border: 1px solid #e05d5d55; }
.sig.mid { background: #e8a33d22; color: var(--accent); border: 1px solid #e8a33d55; }
.sig.lo { background: #4dc3a222; color: var(--accent-2); border: 1px solid #4dc3a255; }
.s-cat { font-family: var(--mono); font-size: 10px; color: var(--ink-3); }
.s-ctry { font-family: var(--mono); font-size: 10px; color: var(--ink-2); }
.s-date { font-family: var(--mono); font-size: 10px; color: var(--ink-3); margin-left: auto; }
.empty { color: var(--ink-3); text-align: center; padding: 40px 20px; font-size: 13px; }
/* ---------- country panel ---------- */
.country-panel {
  position: absolute; right: 16px; top: 16px; z-index: 15; width: 300px;
  background: var(--panel); border: 1px solid var(--line-2); border-radius: var(--r);
  box-shadow: 0 12px 40px rgba(0,0,0,.55); display: none;
  max-height: calc(100% - 32px); overflow-y: auto;
}
.country-panel.open { display: block; }
.cp-head { padding: 14px 16px 10px; border-bottom: 1px solid var(--line); display: flex; align-items: center; gap: 8px; }
.cp-head .x { margin-left: auto; background: none; border: none; color: var(--ink-3); font-size: 16px; cursor: pointer; }
.cp-head .x:hover { color: var(--ink); }
.cp-head h3 { font-size: 15px; }
.cp-iso { font-family: var(--mono); font-size: 10px; color: var(--accent); border: 1px solid var(--line-2); padding: 1px 6px; border-radius: 4px; }
.cp-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; padding: 12px 16px; }
.cp-cell { background: var(--bg-2); border: 1px solid var(--line); border-radius: 6px; padding: 8px 10px; }
.cp-cell .k { font-size: 9.5px; text-transform: uppercase; letter-spacing: .08em; color: var(--ink-3); }
.cp-cell .v { font-family: var(--mono); font-size: 16px; margin-top: 2px; }
.cp-stories { padding: 4px 16px 14px; }
.cp-stories .cs { font-size: 12px; padding: 7px 0; border-bottom: 1px solid var(--line); color: var(--ink-2); }
.cp-stories .cs b { color: var(--ink); font-weight: 500; }
.cp-stories .cs .d { font-family: var(--mono); font-size: 10px; color: var(--ink-3); }
@media (max-width: 1100px) { .main { grid-template-columns: 1fr 320px; } }
</style>
</head>
<body>
<div class="topbar">
  <div class="brand">
    <span class="mark">GDELT ATLAS</span>
    <span class="sub">global news signal · shadow feed</span>
  </div>
  <div class="spacer"></div>
  <div class="live"><span class="dot"></span> SNAPSHOT · STATIC</div>
  <div class="stat"><div class="k">stories</div><div class="v" id="stat-stories">—</div></div>
  <div class="stat"><div class="k">countries</div><div class="v" id="stat-countries">—</div></div>
  <div class="stat"><div class="k">updated</div><div class="v" id="stat-updated">—</div></div>
</div>
<div class="main">
  <div class="map-col">
    <div class="map-head">
      <div class="map-title">
        <h1>Coverage intensity &amp; derived salience by country</h1>
        <span class="src">source: GDELT 2.0 15-minute event exports (keyless bulk route) · <b>salience is derived</b> = 0.6&times;coverage breadth (articles/50) + 0.4&times;|Goldstein|/10 &mdash; a viewer ordering score, NOT the Cloud plan's paid significance metric (its API 403s from this host)</span>
      </div>
      <span class="hint">hover to inspect · click to pin</span>
      <div class="legend">
        <span class="sw" style="background:#141a24"></span>no data
        <span class="sw" style="background:#e8a33d;opacity:.85"></span>signal
      </div>
    </div>
    <div class="map-wrap">
      <svg id="worldmap" viewBox="0 0 1000 500" preserveAspectRatio="xMidYMid meet"></svg>
      <div class="tooltip" id="tooltip"></div>
      <div class="country-panel" id="country-panel"></div>
    </div>
  </div>
  <div class="feed-col">
    <div class="feed-head">
      <div class="row1">
        <h2>Story feed</h2>
        <span class="count" id="feed-count"></span>
      </div>
      <div class="cats" id="cats"></div>
    </div>
    <div class="feed-list" id="feed-list"></div>
  </div>
</div>
<script>
const SNAPSHOT = __SNAPSHOT__;

/* ---------- state ---------- */
let activeCat = null;
let pinned = null;          // iso3
let countryFilter = null;   // iso3 filter for feed

/* ---------- render map ---------- */
const svg = document.getElementById('worldmap');
const tooltip = document.getElementById('tooltip');
const NS = 'http://www.w3.org/2000/svg';

function sigClass(s) {
  if (s == null) return 'lo';
  if (s >= 0.5) return 'hi';
  if (s >= 0.25) return 'mid';
  return 'lo';
}

function initMap() {
  for (const c of SNAPSHOT.countries) {
    const p = document.createElementNS(NS, 'path');
    p.setAttribute('d', c.d);
    p.setAttribute('class', 'country' + (c.stats ? ' has-data' : ''));
    p.dataset.iso = c.iso3;
    p.dataset.name = c.name;
    if (c.stats) {
      p.style.opacity = Math.min(1, 0.35 + (c.stats.avg_sig || 0.05) * 1.6);
    }
    p.addEventListener('mouseenter', () => showTip(c, p));
    p.addEventListener('mousemove', (e) => moveTip(e));
    p.addEventListener('mouseleave', hideTip);
    p.addEventListener('click', () => pinCountry(c.iso3));
    svg.appendChild(p);
  }
}

function showTip(c, p) {
  const s = c.stats;
  if (!s) {
    tooltip.innerHTML = `<div class="t-name">${esc(c.name)}</div><div class="t-row"><span>no coverage in snapshot</span></div>`;
  } else {
    tooltip.innerHTML = `
      <div class="t-name">${esc(c.name)} <span style="color:var(--ink-3);font-family:var(--mono);font-size:10px">${c.iso3}</span></div>
      <div class="t-row"><span>stories</span><b>${s.count}</b></div>
      <div class="t-row"><span>avg salience</span><b>${s.avg_sig}</b></div>
      <div class="t-row"><span>max salience</span><b>${s.max_sig}</b></div>
      <div class="t-row"><span>top category</span><b>${esc(s.top_cat)}</b></div>`;
  }
  tooltip.style.opacity = 1;
}
function moveTip(e) { tooltip.style.left = (e.offsetX + 14) + 'px'; tooltip.style.top = (e.offsetY + 14) + 'px'; }
function hideTip() { tooltip.style.opacity = 0; }

function pinCountry(iso) {
  const panel = document.getElementById('country-panel');
  if (pinned === iso) { closePanel(); return; }
  pinned = iso;
  countryFilter = iso;
  const c = SNAPSHOT.countries.find(x => x.iso3 === iso);
  document.querySelectorAll('#worldmap .country').forEach(p => p.classList.toggle('sel', p.dataset.iso === iso));
  if (!c || !c.stats) {
    panel.innerHTML = `<div class="cp-head"><h3>${esc(c ? c.name : iso)}</h3><button class="x" onclick="closePanel()">×</button></div><div class="empty">No coverage in this snapshot.</div>`;
  } else {
    const s = c.stats;
    const rows = s.top_stories.map(st => `
      <div class="cs"><b>${esc(st.title)}</b> <span class="sig ${sigClass(st.significance)}">${st.significance}</span><div class="d">${esc(st.category)} · ${esc(st.date)}</div></div>`).join('');
    panel.innerHTML = `
      <div class="cp-head"><h3>${esc(c.name)}</h3><span class="cp-iso">${c.iso3}</span><button class="x" onclick="closePanel()">×</button></div>
      <div class="cp-grid">
        <div class="cp-cell"><div class="k">stories</div><div class="v">${s.count}</div></div>
        <div class="cp-cell"><div class="k">avg sig</div><div class="v">${s.avg_sig}</div></div>
        <div class="cp-cell"><div class="k">max sig</div><div class="v">${s.max_sig}</div></div>
        <div class="cp-cell"><div class="k">top cat</div><div class="v" style="font-size:12px">${esc(s.top_cat)}</div></div>
      </div>
      <div class="cp-stories">${rows}</div>`;
  }
  panel.classList.add('open');
  renderFeed();
}
function closePanel() {
  pinned = null; countryFilter = null;
  document.getElementById('country-panel').classList.remove('open');
  document.querySelectorAll('#worldmap .country').forEach(p => p.classList.remove('sel'));
  renderFeed();
}
window.closePanel = closePanel;

/* ---------- feed ---------- */
const catsEl = document.getElementById('cats');
const feedEl = document.getElementById('feed-list');

function catList() {
  const m = {};
  for (const r of SNAPSHOT.feed) m[r.category] = (m[r.category] || 0) + 1;
  return Object.entries(m).sort((a, b) => b[1] - a[1]);
}

function initCats() {
  const cats = catList();
  catsEl.innerHTML = '';
  for (const [cat, n] of cats) {
    const b = document.createElement('button');
    b.className = 'cat' + (activeCat === cat ? ' on' : '');
    b.textContent = `${cat} ${n}`;
    b.onclick = () => {
      activeCat = (activeCat === cat) ? null : cat;
      initCats();
      renderFeed();
    };
    catsEl.appendChild(b);
  }
}

function renderFeed() {
  let list = SNAPSHOT.feed;
  if (activeCat) list = list.filter(r => r.category === activeCat);
  if (countryFilter) list = list.filter(r => r.iso3 === countryFilter);
  document.getElementById('feed-count').textContent = list.length + ' / ' + SNAPSHOT.feed.length;
  if (!list.length) {
    feedEl.innerHTML = '<div class="empty">No stories match the current filter.</div>';
    return;
  }
  feedEl.innerHTML = list.map(r => `
    <div class="story" ${r.url ? `onclick="window.open('${esc(r.url)}','_blank')"` : ''}>
      <div class="s-title">${esc(r.title)}</div>
      <div class="s-meta">
        <span class="sig ${sigClass(r.significance)}">${r.significance}</span>
        <span class="s-cat">${esc(r.category)}</span>
        ${r.country ? `<span class="s-ctry">${esc(r.country)}</span>` : ''}
        <span class="s-date">${esc(r.date)}</span>
      </div>
    </div>`).join('');
}

/* ---------- header stats ---------- */
function initStats() {
  document.getElementById('stat-stories').textContent = SNAPSHOT.total_stories;
  document.getElementById('stat-countries').textContent = SNAPSHOT.covered;
  const d = new Date(SNAPSHOT.generated);
  document.getElementById('stat-updated').textContent = d.toISOString().slice(5, 16).replace('T', ' ');
}

/* ---------- utils ---------- */
function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

/* ---------- boot ---------- */
initMap();
initCats();
renderFeed();
initStats();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
