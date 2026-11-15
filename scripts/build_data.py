"""Daily data build for E-Moto Ride Finder.

Writes:
  trails.geojson  - trails open to motorcycles (Forest Service routes + OpenStreetMap)
  data.json       - parking checks, closure signals, measured snow depth per spot

Rules:
  * A trail is only included if an official source or an OpenStreetMap motorcycle tag says motorcycles are allowed.
  * Status can only be pushed toward "closed" / "check first" by a signal. Nothing here ever marks a spot open.
  * Every parking spot from the Forest Service or DNR is re-checked against the official record each run.
"""
import json, math, re, sys, time, urllib.parse, urllib.request, datetime as dt

UA = {"User-Agent": "emoto-trails (github.com/joemarcouxid/emoto-trails)"}
BBOX = (46.3, -122.3, 49.0, -119.0)  # S, W, N, E: central WA plus the big west-side ORV areas
FS = "https://apps.fs.usda.gov/arcx/rest/services/EDW"
DNR = "https://gis.dnr.wa.gov/site2/rest/services/Recreation/DNR_Recreation_Sites/MapServer/0"


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def get(url, params=None, data=None, timeout=90, tries=3, as_text=False):
    if params:
        url += "?" + urllib.parse.urlencode(params)
    body = urllib.parse.urlencode(data).encode() if data else None
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=body, headers=UA), timeout=timeout) as r:
                raw = r.read().decode("utf-8", "replace")
                return raw if as_text else json.loads(raw)
        except Exception as e:
            last = e
            log(f"  retry {i+1} {url[:90]}: {e}")
            time.sleep(10 * (i + 1))
    raise last


def meters(a, b):  # points as (lon, lat)
    k = 111320
    return math.hypot((a[0] - b[0]) * k * math.cos(math.radians(a[1])), (a[1] - b[1]) * k)


def thin(coords, min_m=12):
    if len(coords) < 3:
        return coords
    out = [coords[0]]
    for c in coords[1:-1]:
        if meters(c, out[-1]) >= min_m:
            out.append(c)
    out.append(coords[-1])
    return out


def num(ref):
    m = re.search(r"(\d{3,4}(?:\.\d)?[A-Z]?)", ref or "")
    return m.group(1) if m else None


SPOTS_FILE = json.load(open("spots.json"))
spots = SPOTS_FILE["spots"]
CAUTION = SPOTS_FILE.get("cautionNos", {})
today = dt.date.today()
data = {"updated": today.isoformat(), "spots": {}, "sources": {}}
for s in spots:
    data["spots"][s["id"]] = {"signals": [], "parking": [], "snow": None}


def signal(sid, level, text, url=None, src=""):
    data["spots"][sid]["signals"].append({"level": level, "text": text, "url": url, "src": src})


# ---------------- 1. OpenStreetMap trails ----------------
osm_feats = []
try:
    b = f"{BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]}"
    q = f"""[out:json][timeout:180];(
      way["highway"~"^(path|track|bridleway|footway|cycleway)$"]["motorcycle"~"^(yes|designated|permissive)$"]({b});
      way["highway"]["name"~"(^| )(ORV|OHV)( |$)|Motorcycle"]["motorcycle"!~"^(no|private)$"]({b});
    );out tags geom;"""
    j = None
    for srv in ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
                "https://overpass.private.coffee/api/interpreter"]:
        try:
            j = get(srv, data={"data": q}, timeout=240, tries=2)
            break
        except Exception as e:
            log("overpass failed", srv, e)
    if j is None:
        raise RuntimeError("all overpass servers failed")
    for el in j["elements"]:
        g = el.get("geometry") or []
        if len(g) < 2:
            continue
        t = el.get("tags", {})
        props = {"src": "osm", "id": el["id"], "name": t.get("name"), "ref": t.get("ref"),
                 "no": num(t.get("ref") or t.get("name")), "hw": t.get("highway"),
                 "surface": t.get("surface"), "moto": t.get("motorcycle")}
        osm_feats.append({"type": "Feature",
                          "geometry": {"type": "LineString", "coordinates": thin([[round(p["lon"], 5), round(p["lat"], 5)] for p in g])},
                          "properties": {k: v for k, v in props.items() if v}})
    data["sources"]["osm"] = f"ok, {len(osm_feats)} segments"
except Exception as e:
    data["sources"]["osm"] = f"failed, kept last copy: {e}"
    try:  # keep the previous OSM lines rather than losing them
        old = json.load(open("trails.geojson"))
        osm_feats = [f for f in old["features"] if f["properties"].get("src", "osm") == "osm"]
        for f in osm_feats:
            f["properties"]["src"] = "osm"
            f["properties"].setdefault("no", num(f["properties"].get("ref") or f["properties"].get("name")))
    except Exception:
        pass

# ---------------- 2. Forest Service trail routes ----------------
# Trail numbers with confirmed motorcycle use: curated from Forest Service maps/brochures (spots.json),
# plus numbers that OpenStreetMap tags as open to motorcycles.
curated = {n for s in spots for n in s.get("trailNos", [])} | set(SPOTS_FILE.get("extraTrailNos", []))
from_osm = {f["properties"]["no"] for f in osm_feats if f["properties"].get("no")}
fs_feats = []
osm_pts = {}
for f in osm_feats:
    n = f["properties"].get("no")
    if n:
        osm_pts.setdefault(n, []).extend(f["geometry"]["coordinates"])
try:
    nos = sorted(curated | from_osm)
    j = get(f"{FS}/EDW_TrailNFSPublish_01/MapServer/0/query", {
        "where": "admin_org LIKE '0617%' AND trail_no IN (" + ",".join(f"'{n}'" for n in nos) + ")",
        "outFields": "trail_name,trail_no,gis_miles",
        "returnGeometry": "true", "outSR": "4326", "geometryPrecision": "5", "f": "json"}, timeout=120)
    for f in j.get("features", []):
        a = f["attributes"]
        n = a["trail_no"]
        why = CAUTION.get(n) or ("Forest Service trail map, brochure or trailhead page" if n in curated else "OpenStreetMap motorcycle tag")
        if "WILDERNESS" in (a["trail_name"] or "").upper():
            continue  # motorcycles are never allowed in wilderness
        for path in f["geometry"]["paths"]:
            if len(path) < 2:
                continue
            if n not in curated:
                # Only keep the part of the official route that OpenStreetMap actually tags for motorcycles
                mid = path[len(path) // 2]
                if not osm_pts.get(n) or min(meters(mid, q) for q in osm_pts[n]) > 300:
                    continue
            fs_feats.append({"type": "Feature",
                             "geometry": {"type": "LineString", "coordinates": thin([[round(x, 5), round(y, 5)] for x, y in path])},
                             "properties": {"src": "usfs", "name": (a["trail_name"] or "").title(), "no": n,
                                            "miles": round(a["gis_miles"] or 0, 1), "why": why, "hw": "path"}})
    data["sources"]["usfs_trails"] = f"ok, {len(fs_feats)} segments, {len({f['properties']['no'] for f in fs_feats})} trails"
except Exception as e:
    data["sources"]["usfs_trails"] = f"failed: {e}"

# Forest Service ATV/ORV routes that run on forest roads (road ids listed per spot)
road_ids = sorted({r for s in spots for r in s.get("roadIds", [])})
if road_ids:
    try:
        j = get(f"{FS}/EDW_RoadBasic_01/MapServer/0/query", {"where": "id IN (" + ",".join(f"'{r}'" for r in road_ids) + ")",
                "outFields": "id,name", "returnGeometry": "true", "outSR": "4326", "geometryPrecision": "5", "f": "json"})
        for f in j.get("features", []):
            a = f["attributes"]
            for path in f["geometry"]["paths"]:
                if len(path) < 2: continue
                fs_feats.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": thin([[round(x, 5), round(y, 5)] for x, y in path])},
                                 "properties": {"src": "usfsroad", "name": f"FS Rd {a['id'][:4]}" + (f"-{a['id'][4:]}" if a['id'][4:] != "000" else "") + (f" ({a['name'].title()})" if a.get("name") else ""),
                                                "no": a["id"], "why": "Forest Service ATV/ORV route", "hw": "track"}})
        data["sources"]["usfs_orv_roads"] = f"ok, {len(j.get('features', []))} roads"
    except Exception as e:
        data["sources"]["usfs_orv_roads"] = f"failed: {e}"

# Drop OSM ways that duplicate a Forest Service route (same trail number); the official route wins.
fs_nos = {f["properties"]["no"] for f in fs_feats}
osm_keep = [f for f in osm_feats if f["properties"].get("no") not in fs_nos]
confirmed = fs_feats + osm_keep

# ---------------- 2a. DNR / WDFW green-dot roads ----------------
# 10 green-dot road, 20 green-dot jeep trail, 22 seasonal green-dot road = open to ORVs.
# 30 road management area access road = street-legal vehicles only. 21 other jeep trail = not green dot (skipped).
street_only = []
try:
    GD = "https://services.arcgis.com/4x406oNViizbGo13/arcgis/rest/services/Adding_GreenDotRoads/FeatureServer/0/query"
    off, gd = 0, 0
    while True:
        j = get(GD, {"where": "GREENDOT_STATUS IN (10,20,22,30)", "outFields": "ROAD_NM,GREENDOT_STATUS,SEASONAL",
                     "returnGeometry": "true", "outSR": "4326", "geometryPrecision": "5", "resultOffset": off,
                     "resultRecordCount": 1000, "f": "json"}, timeout=120)
        feats = j.get("features", [])
        for f in feats:
            a = f["attributes"]; st = a.get("GREENDOT_STATUS")
            for path in (f.get("geometry") or {}).get("paths", []):
                if len(path) < 2: continue
                feat = {"type": "Feature", "geometry": {"type": "LineString", "coordinates": thin([[round(x, 5), round(y, 5)] for x, y in path])},
                        "properties": {k: v for k, v in {"src": "greendot", "name": a.get("ROAD_NM"), "gd": st,
                                       "seasonal": 1 if (st == 22 or a.get("SEASONAL") == 1) else None, "hw": "track"}.items() if v is not None}}
                if st == 30:
                    feat["properties"]["street"] = 1; street_only.append(feat)
                else:
                    confirmed.append(feat); gd += 1
        if not j.get("exceededTransferLimit") and len(feats) < 1000: break
        off += len(feats)
    data["sources"]["greendot"] = f"ok, {gd} ORV segments, {len(street_only)} street-legal-only"
except Exception as e:
    data["sources"]["greendot"] = f"failed: {e}"

# Tag each confirmed trail with the spots it belongs to (trail number listed for the spot, or within 8 km of its parking)
def spot_points(s):
    return [(p["lon"], p["lat"]) for p in s.get("parking", [])] or [(s["lon"], s["lat"])]
for f in confirmed:
    pr = f["properties"]; cs = f["geometry"]["coordinates"]; mid = cs[len(cs) // 2]
    ids = [s["id"] for s in spots if (pr.get("no") and pr["no"] in s.get("trailNos", []))
           or min(meters(mid, q) for q in spot_points(s)) <= 8000]
    if ids: pr["spots"] = ids
    pr["len"] = round(sum(meters(cs[i], cs[i + 1]) for i in range(len(cs) - 1)) / 1609.34, 2)

json.dump({"type": "FeatureCollection", "updated": today.isoformat(), "features": confirmed},
          open("trails.geojson", "w"), separators=(",", ":"))
log(f"trails: {len(fs_feats)} usfs + {len(osm_keep)} osm")

# ---------------- 2b. Branch trails near each spot (motorcycle use NOT confirmed) ----------------
# Shown in gray so riders can see where trails split, without the app suggesting they're legal.
def norm(n):
    return re.sub(r"\b(road|rd)\b", "rd", (n or "").lower()).strip()
gd_names = {norm(f["properties"].get("name")) for f in confirmed + street_only
            if f["properties"].get("src") == "greendot" and f["properties"].get("name")}
ctx = []
conf_osm_ids = {f["properties"].get("id") for f in osm_feats}
try:
    around = "".join(f'way["highway"~"^(path|track|footway|bridleway)$"](around:6000,{lat},{lon});'
                     for s in spots if s.get("trailNos") for lon, lat in spot_points(s))
    q = f"[out:json][timeout:180];({around});out tags geom;"
    j = None
    for srv in ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
                "https://overpass.private.coffee/api/interpreter"]:
        try:
            j = get(srv, data={"data": q}, timeout=240, tries=2); break
        except Exception as e:
            log("overpass (branches) failed", srv, e)
    if j is None: raise RuntimeError("all overpass servers failed")
    seen = set()
    for el in j["elements"]:
        if el["id"] in conf_osm_ids or el["id"] in seen: continue
        seen.add(el["id"])
        g = el.get("geometry") or []
        if len(g) < 2: continue
        t = el.get("tags", {})
        no = num(t.get("ref") or t.get("name"))
        if no and no in fs_nos: continue  # already drawn as a confirmed Forest Service route
        if t.get("motorcycle") in ("yes", "designated", "permissive"): continue
        if t.get("name") and norm(t["name"]) in gd_names: continue  # OpenStreetMap copy of a green-dot road
        props = {"src": "osm", "id": el["id"], "name": t.get("name"), "ref": t.get("ref"), "hw": t.get("highway"),
                 "moto": t.get("motorcycle"), "access": t.get("access"), "old": t.get("old_name")}
        ctx.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": thin([[round(p["lon"], 5), round(p["lat"], 5)] for p in g], 15)},
                    "properties": {k: v for k, v in props.items() if v}})
    data["sources"]["branches"] = f"ok, {len(ctx)} segments"
except Exception as e:
    data["sources"]["branches"] = f"failed, kept last copy: {e}"
    try:
        ctx = [f for f in json.load(open("branches.geojson"))["features"] if not f["properties"].get("street")]
    except Exception:
        ctx = []
json.dump({"type": "FeatureCollection", "updated": today.isoformat(), "features": ctx + street_only},
          open("branches.geojson", "w"), separators=(",", ":"))



# ---------------- 3. Parking checks + official site status ----------------
def fs_site(rid):
    j = get(f"{FS}/EDW_RecreationOpportunities_01/MapServer/0/query",
            {"where": f"recareaid={int(rid)}", "outFields": "recareaname,openstatus",
             "returnGeometry": "true", "outSR": "4326", "f": "json"})
    f = (j.get("features") or [None])[0]
    return f and {"lon": f["geometry"]["x"], "lat": f["geometry"]["y"],
                  "status": (f["attributes"].get("openstatus") or "").lower()}


def dnr_site(name):
    j = get(f"{DNR}/query", {"where": f"UPPER(NAME) LIKE UPPER('{name}%')", "outFields": "NAME,SITE_STATUS",
                             "returnGeometry": "true", "outSR": "4326", "f": "json"})
    f = (j.get("features") or [None])[0]
    if not f:
        return None
    st = f["attributes"].get("SITE_STATUS")
    return {"lon": f["geometry"]["x"], "lat": f["geometry"]["y"],
            "status": {"O": "open", "C": "closed"}.get(st, str(st or "").lower())}


for s in spots:
    for p in s.get("parking", []):
        rec = {"name": p["name"], "check": "not checked"}
        try:
            if p["src"] in ("usfs", "dnr"):
                off = fs_site(p["srcId"]) if p["src"] == "usfs" else dnr_site(p["srcId"])
                agency = "Forest Service" if p["src"] == "usfs" else "DNR"
                if not off:
                    rec["check"] = "missing"
                    signal(s["id"], "warn", f"The {agency} record for {p['name']} wasn't found in today's check.", p.get("url"), "parking check")
                else:
                    moved = meters((p["lon"], p["lat"]), (off["lon"], off["lat"]))
                    rec.update(check="ok" if moved <= 75 else "moved", movedM=round(moved),
                               lat=round(off["lat"], 5), lon=round(off["lon"], 5), status=off["status"])
                    if moved > 75:
                        signal(s["id"], "warn", f"The {agency} moved its location for {p['name']} by {round(moved)} m. Directions now use the new location.", p.get("url"), "parking check")
                    if off["status"] == "closed":
                        signal(s["id"], "closed", f"{p['name']} is marked closed by the {agency}.", p.get("url"), "official site status")
            elif p["src"] == "parks":
                rec["check"] = "official"
            else:
                rec["check"] = "multi-source"
        except Exception as e:
            rec["check"] = f"error: {e}"
        data["spots"][s["id"]]["parking"].append(rec)
data["sources"]["parking"] = "ok"

# ---------------- 4. Active wildfires near each spot ----------------
try:
    for s in spots:
        j = get("https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/WFIGS_Interagency_Perimeters_Current/FeatureServer/0/query", {
            "geometry": f"{s['lon']},{s['lat']}", "geometryType": "esriGeometryPoint", "inSR": "4326",
            "distance": "12000", "units": "esriSRUnit_Meter", "spatialRel": "esriSpatialRelIntersects",
            "outFields": "poly_IncidentName,attr_PercentContained", "returnGeometry": "false", "f": "json"})
        if "error" in j:
            raise RuntimeError(j["error"])
        for f in j.get("features", []):
            a = f["attributes"]
            pc = a.get("attr_PercentContained")
            signal(s["id"], "closed",
                   f"Active wildfire within about 7 miles: {a.get('poly_IncidentName') or 'unnamed'}"
                   + (f" ({int(pc)}% contained)" if pc is not None else "") + ". Expect closures.",
                   "https://inciweb.wildfire.gov/", "national fire perimeters")
    data["sources"]["fires"] = "ok"
except Exception as e:
    data["sources"]["fires"] = f"failed: {e}"

# ---------------- 5. Forest Service alerts that mention a spot ----------------
try:
    html = get("https://www.fs.usda.gov/r06/okanogan-wenatchee/alerts", as_text=True, timeout=60)
    alerts, seen_titles = [], set()
    for m in re.finditer(r'<a[^>]+href="([^"]*/alerts/[^"#]+)"[^>]*>(.*?)</a>(.{0,800})', html, re.S | re.I):
        title = re.sub(r"<[^>]+>|\s+", " ", m.group(2)).strip()
        blurb = re.sub(r"<[^>]+>|\s+", " ", m.group(3)).strip()
        if len(title) < 12 or title in seen_titles:
            continue
        seen_titles.add(title)
        alerts.append((title, blurb, urllib.parse.urljoin("https://www.fs.usda.gov", m.group(1))))
    for s in spots:
        for title, blurb, url in alerts:
            text = f"{title} {blurb}"
            hit = next((k for k in s.get("keywords", [])
                        if re.search(rf"(?<![\w.]){re.escape(k)}(?![\w.])", text, re.I)), None)
            if hit:
                m = re.search(r"Start Date:?\s*([A-Z][a-z]+ \d{1,2}, \d{4})", blurb)
                if not m:
                    try:
                        page = re.sub(r"<[^>]+>|\s+", " ", get(url, as_text=True, timeout=45, tries=2))
                        m = re.search(r"Start Date:?\s*([A-Z][a-z]+ \d{1,2}, \d{4})", page)
                    except Exception:
                        m = None
                start = None
                if m:
                    try: start = dt.datetime.strptime(m.group(1), "%B %d, %Y").date()
                    except ValueError: start = None
                if start and (today - start).days > 365:
                    signal(s["id"], "info", f"Standing rule since {start.year}: {title}", url, "Forest Service alerts")
                else:
                    signal(s["id"], "warn", f"Forest Service alert mentions {hit}: {title}" + (f" (since {start:%b %d, %Y})" if start else ""), url, "Forest Service alerts")
    data["sources"]["usfs_alerts"] = f"ok, {len(alerts)} alerts scanned"
except Exception as e:
    data["sources"]["usfs_alerts"] = f"failed: {e}"

# ---------------- 6. Measured snow depth (SNOTEL) ----------------
try:
    A = "https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1"
    st = get(f"{A}/stations", {"stateCds": "WA", "networkCds": "SNTL", "activeOnly": "true",
                               "returnForecastPointMetadata": "false", "returnReservoirMetadata": "false",
                               "returnStationElements": "false"})
    st = [x for x in st if x.get("latitude") and x.get("longitude")]
    near = {}
    for s in spots:
        best = min(st, key=lambda x: meters((s["lon"], s["lat"]), (x["longitude"], x["latitude"])))
        d = meters((s["lon"], s["lat"]), (best["longitude"], best["latitude"]))
        if d <= 40000:
            near[s["id"]] = (best, d)
    trip = sorted({b["stationTriplet"] for b, _ in near.values()})
    depth = {}
    if trip:
        j = get(f"{A}/data", {"stationTriplets": ",".join(trip), "elements": "SNWD", "duration": "DAILY",
                              "beginDate": (today - dt.timedelta(days=5)).isoformat(), "endDate": today.isoformat()})
        for row in j:
            vals = [v for d in row.get("data", []) for v in d.get("values", []) if v.get("value") is not None]
            if vals:
                depth[row["stationTriplet"]] = vals[-1]
    for sid, (b, d) in near.items():
        v = depth.get(b["stationTriplet"])
        if v:
            data["spots"][sid]["snow"] = {"station": b["name"].title(), "elevFt": round(b.get("elevation") or 0),
                                          "miles": round(d / 1609.34, 1), "depthIn": v["value"], "date": str(v["date"])[:10]}
    data["sources"]["snotel"] = f"ok, {len(near)} spots near a station, {len(depth)} readings"
except Exception as e:
    data["sources"]["snotel"] = f"failed: {e}"

json.dump(data, open("data.json", "w"), indent=1)
log(json.dumps(data["sources"], indent=1))
