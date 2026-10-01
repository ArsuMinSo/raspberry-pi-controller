# Floor Map — Summary

## Concept

Map kiosk floor position using existing WiFi/BLE hardware on each Pi. Access points (APs) are fixed
anchors placed manually on a canvas (drag + save x/y). Pi position is *computed*, not manual — a
signal-weighted centroid of the placed APs visible in its latest WiFi scan. BLE scans are logged for
informational purposes only (ambient devices have no fixed position, so can't be placed on the map).

## How it works

1. Operator hits WiFi/BLE scan (manual trigger only, no schedule) from the web app.
2. Server SSHes into each targeted Pi and runs one command: `iw dev wlan0 scan` or
   `bluetoothctl --timeout 10 scan on` (same mechanism as any other Execute action — no Pi-side agent).
3. Output is parsed server-side (`backend/services/floor_map.py`) into per-AP or per-device readings.
4. WiFi readings are stored in `wifi_scans`; any never-seen BSSID auto-registers in `access_points`
   with `x/y = NULL` ("unplaced", shows in a staging list until dragged onto the map).
5. BLE readings are stored in `ble_scans` — logged, never used for positioning.
6. `GET /floor-map` returns AP anchors + each Pi's computed position (weighted centroid, or `null` if
   no placed AP was visible in the lookback window).

## What was built

- `migrations/008_floor_map.sql`, `009_floor_map_actions.sql` — 3 new tables + widened action-type check
- `backend/models.py` — `AccessPoint`, `WifiScan`, `BleScan`
- `backend/schemas.py` — floor-map DTOs
- `backend/services/floor_map.py` — scan parsing, job orchestration, centroid calc
- `backend/routes/floor_map.py` — `/api/v1/floor-map/*` (wifi-scan, ble-scan, map read, AP placement, per-Pi BLE list)
- `tests/test_floor_map.py` — parsing unit tests + job/route/position-calc tests
- `web/src/app/pages/floor-map.page.ts` — SVG canvas, draggable AP placement, scan trigger buttons
- Route added at `/mapplan` — **intentionally not linked in the side menu**, reachable by URL only

Full design detail and locked decisions: `plan_floor_map.md`.

## Key locked decisions

- Manual scan trigger only (v1), single floor, APs auto-register unplaced on first sighting
- Position = weighted centroid approximation, not calibrated trilateration
- `iw` scanning needs `setcap cap_net_raw,cap_net_admin+eip` on `/usr/sbin/iw` (one-time provisioning,
  done via TUI's sudo-piped exec — no passwordless sudo added); `bluetoothctl` needed no privilege change;
  `nmcli` dropped (NetworkManager not running on kiosk image)

## Open risks (see `TODO.md` for the tracked checklist)

- **BLE scanning logs bystanders' device MAC + name — likely GDPR personal data**, since it enables
  tracking a device's position over time even with no other identifying info. Needs a real compliance
  check before use anywhere with non-staff foot traffic.
- That data also lands in the append-only `actions_log`, conflicting with right-to-erasure if ever needed.
- No retention/pruning exists for any time-series table in this codebase (`health_samples` included) —
  everything grows forever.
- `setcap` widens `iw`'s capability for any process on the kiosk, not just the controller's SSH session.

## Status

Backend (migrations, models, schemas, service, routes) and frontend page are implemented. Migration
`008` is applied on prod; `009` still needs `scripts/setup_db.sh` run on the server. Not yet verified
against the real pytest suite (no local Python env on this machine — needs running on the server).
