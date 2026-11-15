# E-Moto Ride Finder

Where to ride a Sur-Ron or Talaria near Wenatchee. Lists legal motorcycle trail areas sorted by distance from you, with open/closed status, an estimated trail condition from recent weather, difficulty, and ratings.

## Files
- `index.html` – the app
- `status.json` – post closures or openings here; the app reads it every time you tap Refresh

## Posting a closure
Edit `status.json` on GitHub. Example:
```json
"devils-gulch": { "status": "closed", "note": "Fire closure – see Forest Service alerts." }
```
Spot ids: devils-gulch, beehive, mission-ridge, tronsen, mad-river, entiat-ridge, naneum, taneum, moses-dunes, beverly

## Turn on GitHub Pages
Settings → Pages → Deploy from branch → `main` / root.

## Trail map
`trails.geojson` holds every trail OpenStreetMap lists as open to motorcycles in this area. A GitHub Action (`.github/workflows/update-trails.yml`) refreshes it every Monday. You can also run it by hand from the Actions tab.
