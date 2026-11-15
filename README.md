# E-Moto Ride Finder

Where to ride a Sur-Ron or Talaria near Wenatchee. Lists legal motorcycle trail areas sorted by distance from you, with open/closed status, an estimated trail condition from recent weather, difficulty, and ratings.

## Files
- `index.html` – the app
- `status.json` – post closures or openings here; the app reads it every time you tap Refresh

## How the data works
- `spots.json` – riding spots and **verified parking**. Every parking entry is an official Forest Service or DNR site, or a location 2+ independent sources agree on. Directions always use the exact coordinates.
- `data.json` – rebuilt daily by `.github/workflows/update-trails.yml` (`scripts/build_data.py`):
  - re-checks every official parking location against the Forest Service / DNR record and flags any that moved or disappeared
  - closure signals: official site closed flags, active wildfire perimeters within ~7 miles, Forest Service alerts that mention a spot's trails
  - measured snow depth from the nearest SNOTEL sensor
- `trails.geojson` – official Forest Service routes for trails with confirmed motorcycle use, plus OpenStreetMap trails tagged open to motorcycles.

Signals can only mark a spot "closed" or "check first". Nothing marks a spot open except its normal season dates.

## Posting a closure
Edit `status.json` on GitHub. Example:
```json
"devils-gulch": { "status": "closed", "note": "Fire closure – see Forest Service alerts." }
```
Spot ids: devils-gulch, beehive, mission-ridge, stemilt, mitchell-creek, methow-sawtooth, ahtanum, reiter, walker-valley, elbe-hills, tronsen, mad-river, chiwawa, naneum, taneum, little-naches, moses-dunes, beverly

## Turn on GitHub Pages
Settings → Pages → Deploy from branch → `main` / root.
