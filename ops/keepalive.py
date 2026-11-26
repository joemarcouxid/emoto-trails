"""Keep free-plan services awake. Run by .github/workflows/keep-services-awake.yml.

Supabase pauses free projects after a week with no database activity. A tiny read
(limit 1) from a public table counts as activity. Fails loudly so GitHub emails you.
"""
import json, sys, urllib.request

cfg = json.load(open("ops/keepalive.json"))
failed = []
for p in cfg.get("supabase", []):
    url = f"{p['url'].rstrip('/')}/rest/v1/{p['table']}?select=*&limit=1"
    req = urllib.request.Request(url, headers={"apikey": p["key"], "User-Agent": "keepalive (github.com/joemarcouxid/emoto-trails)"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            print(f"OK   Supabase {p['name']}: HTTP {r.status}")
    except Exception as e:
        print(f"FAIL Supabase {p['name']}: {e}")
        failed.append(p["name"])
if failed:
    sys.exit("Could not reach: " + ", ".join(failed) + ". If a project shows 'paused' in the Supabase dashboard, restore it there.")
