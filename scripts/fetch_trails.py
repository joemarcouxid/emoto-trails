"""Download trails open to motorcycles from OpenStreetMap and save them as trails.geojson."""
import json, math, sys, time, urllib.parse, urllib.request

BBOX = "46.7,-121.4,48.4,-119.1"  # south, west, north, east: Ellensburg to Chelan, Cascades to Moses Lake
QUERY = f"""
[out:json][timeout:180];
(
  way["highway"~"^(path|track|bridleway|footway|cycleway)$"]["motorcycle"~"^(yes|designated|permissive)$"]({BBOX});
  way["highway"]["name"~"(^| )(ORV|OHV)( |$)|Motorcycle"]["motorcycle"!~"^(no|private)$"]({BBOX});
);
out tags geom;
"""
SERVERS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

def fetch():
    data = urllib.parse.urlencode({"data": QUERY}).encode()
    for attempt in range(3):
        for url in SERVERS:
            try:
                req = urllib.request.Request(url, data=data, headers={"User-Agent": "emoto-trails (github.com/joemarcouxid/emoto-trails)"})
                with urllib.request.urlopen(req, timeout=240) as r:
                    return json.load(r)
            except Exception as e:
                print(f"{url} failed: {e}", file=sys.stderr)
        time.sleep(30)
    sys.exit("All Overpass servers failed")

def meters(a, b):
    k = 111320
    return math.hypot((a[0] - b[0]) * k * math.cos(math.radians(a[1])), (a[1] - b[1]) * k)

def thin(coords, min_m=12):
    out = [coords[0]]
    for c in coords[1:-1]:
        if meters(c, out[-1]) >= min_m:
            out.append(c)
    out.append(coords[-1])
    return out

def main():
    j = fetch()
    feats = []
    for el in j.get("elements", []):
        geom = el.get("geometry")
        if not geom or len(geom) < 2:
            continue
        coords = thin([[round(p["lon"], 5), round(p["lat"], 5)] for p in geom])
        t = el.get("tags", {})
        feats.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {k: v for k, v in {
                "id": el["id"], "name": t.get("name"), "ref": t.get("ref"),
                "hw": t.get("highway"), "surface": t.get("surface"),
                "moto": t.get("motorcycle"), "access": t.get("access"),
            }.items() if v},
        })
    out = {"type": "FeatureCollection", "updated": time.strftime("%Y-%m-%d"), "features": feats}
    with open("trails.geojson", "w") as f:
        json.dump(out, f, separators=(",", ":"))
    print(f"Saved {len(feats)} trail segments")

if __name__ == "__main__":
    main()
