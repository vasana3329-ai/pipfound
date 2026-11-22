# pipfound Archive & PWA Feature Reference

## Overview
Added two new features to the pipfound SMC/ICT analyzer app:
1. **📊 آرشیو اخبار** – button showing already-announced economic news (last 6 hours) with full analysis (direction per pair, gold/silver impact, beat/miss scenarios) inside the app, not a new tab; data auto-purges after 6h.
2. **🔄 بروزرسانی داده‌ها** – refresh button that re-fetches live data via AJAX without page reload, plus PWA install support (manifest, service worker, icons) so the app can be installed locally and work offline.

## Files Modified/Created
- `app.py` – added:
  - Archive button (`#archiveBtn`, class `ab-btn`) after `fundBtn` in toolbar
  - Refresh button (`#refreshBtn`, class `rfr-btn`) after `fundBtn`
  - `/api/fundamental-archive?hours=6` route returning `FUND.build(hours=hours)` filtered JSON
  - JavaScript handlers for both buttons (AJAX fetch, modal render, TTL expiry)
  - PWA constants: `MANIFEST_JSON`, `SERVICE_WORKER_JS`
  - Service worker registration (`if('serviceWorker' in navigator...)`)
  - `/api/health` and `/api/fundamental-archive` routes verified via curl

- Generated icons in `scripts/`:
  - `icon-192.png`, `icon-512.png`, `icon-180.png`
  - maskable variants: `icon-192-mask.png`, `icon-512-mask.png`

- `manifest.webmanifest` and `sw.js` served by the app at `http://127.0.0.1:8787/`

## Endpoint Details
- **GET `/api/fundamental-archive?hours=6`**
  - Calls `FUND.build(hours=hours)` and returns filtered, formatted archive JSON
  - Results stored in `window._archive` with TTL 6 hours, auto-expired
  - Returns JSON: `{"events": [...], "count": N}` where each event has `title_fa`, `tehran_short`, `direction`, `gold_silver_impact`, `beat_miss`

- **GET `/api/refresh`** (AJAX re-fetch)
  - Re-invokes `run()` via fetch, avoiding `location.reload()`
  - Captures latest data in `window._last`
  - Spinner persists, no page reload (verified in preview)

## UI Elements
- **Archive button** (📁 آرشیو اقتصادی): positioned after Fundamental button in toolbar
  - Click → fetches `/api/fundamental-archive?hours=6` → displays results in modal/div inside app
  - Persian RTL-friendly labels
  
- **Refresh button** (🔄 بروزرسانی داده‌ها): positioned after Fundamental button in toolbar
  - Click → AJAX fetch of live data → analysis card refreshed, page stays alive
  - Uses `window._last` to capture latest analysis data

## PWA Strategy
- **network-first** for `/api/*` (ensures fresh data from server)
- **cache-first** for icons & static assets (`manifest.webmanifest`, `sw.js`)
- Service worker registered before `</script>` tag
- App installable locally; works offline for cached assets

## Archive TTL Behavior
- Data stored in `window._archive` with 6-hour TTL
- Automatically expires after 6 hours; user can refresh via the refresh button
- `fundamental_report.md` contains a sample archive report for reference

## Testing
- `curl -s http://127.0.0.1:8787/api/health` → 200
- `curl -s http://127.0.0.1:8787/manifest.webmanifest` → 200
- `curl -s http://127.0.0.1:8787/sw.js` → 200
- `curl -s "http://127.0.0.1:8787/api/fundamental-archive?hours=6"` → 200 with valid JSON
- Desktop preview confirmed: refresh button keeps page alive (spinner persists, no reload)
- Desktop preview confirmed: archive button shows last-6-h news with direction per pair, gold/silver impact, beat/miss scenarios in-app

## Known Constraints
- CPU-light: small walk, single-threaded, `nice -n 19`
- Server port 8787 (`http://127.0.0.1:8787/`)
- User language: Persian (UI RTL)
- Two personas: trader + programmer
- Principle: Data not guess
- Approval threshold 70%, RR ≥ 1:2, target 2-3R