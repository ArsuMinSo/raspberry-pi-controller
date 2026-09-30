# Floor Map — Scoped Plan

> Scope: WiFi/BLE scan capture → RSSI-based Pi position estimate → draggable/saveable AP+Pi map view
> Excluded: real trilateration (path-loss calibration), BLE-anchor positioning, multi-floor support (v2)
> Depends on: existing `raspberries` table, `ssh_executor`, migration chain (next = `008`)

---

## 1. Concept

- **Access points = anchors.** Fixed real-world positions, placed manually once (drag on map, save x/y).
- **Pis = fixed but computed.** Position = weighted centroid of visible AP anchors, weighted by RSSI. Recomputed each scan; not manually dragged (v1).
- **BLE ambient devices = informational only.** No known anchor position → cannot place on map. Logged per-Pi (count/list), not rendered as nodes in v1.
- **Graph is a real floor map, not a force-directed layout** — because AP coords are fixed/known, no spring simulation needed for anchors. (Springs mentioned in original mindplay only made sense before anchors had fixed coords; dropped.)

---

## 2. DB Schema — migration `008_floor_map.sql`

```sql
-- ─── 008: floor map (AP anchors + wifi/ble scans) ──────────────────────────

CREATE TABLE IF NOT EXISTS access_points (
    bssid           VARCHAR(17) PRIMARY KEY,       -- xx:xx:xx:xx:xx:xx, lowercase
    ssid            VARCHAR(255),
    x               DOUBLE PRECISION,               -- NULL until placed on map
    y               DOUBLE PRECISION,
    placed_by_user_id INTEGER REFERENCES users (id),
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS wifi_scans (
    id              SERIAL PRIMARY KEY,
    mac             VARCHAR(17)  NOT NULL REFERENCES raspberries (mac) ON DELETE CASCADE,
    bssid           VARCHAR(17)  NOT NULL,          -- not FK'd — AP may be seen before it's registered
    rssi            SMALLINT     NOT NULL,          -- dBm, e.g. -63
    timestamp       TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ble_scans (
    id              SERIAL PRIMARY KEY,
    mac             VARCHAR(17)  NOT NULL REFERENCES raspberries (mac) ON DELETE CASCADE,
    device_mac      VARCHAR(17)  NOT NULL,
    device_name     VARCHAR(255),
    rssi            SMALLINT,
    timestamp       TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_wifi_scans_mac_ts   ON wifi_scans (mac, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_wifi_scans_bssid    ON wifi_scans (bssid);
CREATE INDEX IF NOT EXISTS idx_ble_scans_mac_ts    ON ble_scans (mac, timestamp DESC);
```

Only latest scan per Pi matters for the live map — query `DISTINCT ON (bssid) ... ORDER BY bssid, timestamp DESC` scoped to a lookback window (e.g. last 5 min), same pattern as `health_samples`.

---

## 3. Pi-side scan (executed via existing SSH executor, not a Pi-side daemon)

Same model as health checks: server SSHes in, runs a one-shot script, parses stdout. No new agent on the Pi.

- WiFi: `iw dev wlan0 scan | awk '/BSS/{bssid=$2} /SSID:/{ssid=$2} /signal:/{print bssid, $2, ssid}'` — confirmed working unprivileged after `setcap cap_net_raw,cap_net_admin+eip /usr/sbin/iw` (see §Provisioning). `nmcli` dropped — NetworkManager not running on kiosk image, no reason to depend on it.
- BLE: `bluetoothctl --timeout 10 scan on` — confirmed working unprivileged (bluez D-Bus scan doesn't need root/sudo/capabilities at all, unlike `iw`).
- Both wrapped as one script `scan_floor.sh` (or two), output as `bssid,rssi,ssid` / `mac,rssi,name` lines → parsed server-side into `wifi_scans` / `ble_scans` rows.

**Real output format (observed on `00-006`), parser must handle:**
- Every colored line is wrapped in control bytes: `\x01\x1B[0;9Xm\x02TAG\x01\x1B[0m\x02 rest...` — strip the `\x01...\x02` wrapper + ANSI SGR codes before matching.
- Device first-seen: `[NEW] Device <MAC> <name-or-mac-with-dashes>`.
- RSSI arrives later, separately, as: `[CHG] Device <MAC> RSSI: <int>` — must join by MAC against the `NEW` line, not read inline.
- RSSI is async/sporadic — not every device seen in a 10s window gets a `CHG RSSI` line. Expect partial RSSI coverage per scan; that's normal, not a bug. Rows with no RSSI still get logged (rssi nullable in `ble_scans`, already schema'd that way).

---

## 4. Backend

### Service: `backend/services/floor_map.py`
- `run_wifi_scan(mac) -> list[WifiScanReading]` — SSH exec + parse, insert rows
- `run_ble_scan(mac) -> list[BleScanReading]` — SSH exec + parse, insert rows
- `compute_pi_position(mac) -> tuple[float, float] | None`
  - Pull latest `wifi_scans` rows for `mac` within lookback window
  - Join to `access_points` where `x`/`y` not null
  - If < 1 placed AP visible → return `None` (unplaceable, frontend shows Pi off-map / list-only)
  - Weight `w_i = 1 / rssi_to_distance(rssi_i)^2` (simple inverse-square on a rough log-distance path-loss estimate, or just `1/|rssi|` as v1 stand-in — document that this is an approximation, not calibrated trilateration)
  - `pos = Σ(w_i * ap_pos_i) / Σ(w_i)`

### Models (`backend/models.py` additions)
- `AccessPoint` (bssid PK, ssid, x, y, placed_by_user_id, created_at, updated_at)
- `WifiScan` (id, mac FK, bssid, rssi, timestamp)
- `BleScan` (id, mac FK, device_mac, device_name, rssi, timestamp)

### Schemas (`backend/schemas.py` additions)
- `AccessPointOut`, `AccessPointPositionUpdate {x, y}`
- `FloorMapPiNode {position, mac, x, y | null, last_scan_at}`
- `FloorMapResponse {access_points: [...], pis: [...]}`
- `BleDeviceSeen {device_mac, device_name, rssi, timestamp}` (for per-Pi BLE list endpoint)

### Routes: `backend/routes/floor_map.py`
| Method | Path | Role | Notes |
|--------|------|------|-------|
| `POST` | `/discovery/wifi-scan` | operator+ | Body `{pis: [...]}` or `{all: true}` — triggers scan via SSH executor, same async/action pattern as `/health/trigger` |
| `POST` | `/discovery/ble-scan` | operator+ | same pattern |
| `GET`  | `/floor-map` | viewer+ | Returns `FloorMapResponse` — APs w/ coords + Pis w/ computed coords |
| `PATCH`| `/floor-map/ap/{bssid}` | operator+ | Body `{x, y}` — drag-save from UI |
| `GET`  | `/floor-map/pi/{position}/ble` | viewer+ | Last BLE scan device list for one Pi |

Wire into `backend/main.py` router include, same as existing route modules.

---

## 5. Frontend (Angular/Ionic, `web/src`)

New page `web/src/app/floor-map/` (matches existing `reactor`-style module, per recent canvas-based dashboard work).

- Canvas or SVG layer (reuse whatever the reactor view already uses for perf/consistency — check `web/src/app/reactor` before picking a new lib).
- AP nodes: draggable, `pointerup` → `PATCH /floor-map/ap/{bssid}` with new x/y.
- Pi nodes: read-only position, greyed out / "unplaced" badge if `x/y == null` (no visible placed AP).
- Poll `GET /floor-map` on interval (reuse existing dashboard auto-refresh pattern).
- Unplaced APs (seen in scans, never dragged) shown in a side list, drag from list onto canvas to place for the first time.

---

## 6. Implementation Order

| Step | File(s) | What to do |
|------|---------|-----------|
| 0 | — (TUI Execute screen, Sudo checkbox) | **Gate — cleared.** `setcap cap_net_raw,cap_net_admin+eip /usr/sbin/iw` applied once across all kiosks via TUI's sudo-piped exec (password typed once, never stored). `iw dev wlan0 scan` confirmed unprivileged. `nmcli` dropped (NetworkManager not running on image). `bluetoothctl --timeout 10 scan on` confirmed unprivileged, no setcap needed. Ready for step 1. Separately check why `00-005`/`00-008` returned empty (likely just unreachable, not a capability gap). |
| 1 | `migrations/008_floor_map.sql` | DDL above |
| 2 | `backend/models.py` | `AccessPoint`, `WifiScan`, `BleScan` |
| 3 | `backend/schemas.py` | DTOs above |
| 4 | `backend/services/floor_map.py` | scan exec + parse + upsert-AP-on-first-sight (x/y null) + `compute_pi_position` |
| 5 | `backend/routes/floor_map.py` | 5 endpoints above — scan triggers are manual-only (button/POST), no scheduler wiring |
| 6 | `backend/main.py` | include router |
| 7 | `tests/test_floor_map.py` | parser unit tests + centroid math + route tests (mock SSH) |
| 8 | `web/src/app/floor-map/` | canvas page: placed APs draggable, unplaced APs listed on the side (drag onto canvas to place), Pi nodes read-only |
| 9 | wiki: API Reference, Database Schema pages | per working agreement, before commit |

---

## Key Design Decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| Position algorithm v1 | Weighted centroid, not trilateration | No path-loss calibration data yet; ship rough view first |
| AP placement | Manual drag, not auto-solved | Positions "will be mapped" per user — treat as ground truth anchor, not estimated |
| Pi placement | Computed, not draggable | Pi position is the thing being measured; dragging it would hide bad signal data instead of surfacing it |
| BLE devices | Logged, not plotted | No fixed anchor for ambient BLE devices → no valid position math |
| Scan trigger | Server-initiated SSH, manual only (v1) | Matches existing arch; no new Pi-side daemon/push, no scheduler wiring needed yet |
| Floor scope | Single floor (v1) | No `floor_id` field, no floor switcher — keep schema/UI simple until multi-site need is real |
| AP registration | Auto, from first scan sighting | AP row created with `x/y = null` the moment any Pi sees its BSSID; admin drags it in later — no manual pre-entry step |
| Scan storage | Time-series table, latest-per-window read | Same pattern as `health_samples` — proven, no new pattern to review |

---

## Open Risks

1. Kiosk image may lack `bluez`/sudo perms for scan commands — needs on-device check before coding service layer.
2. Indoor RSSI is noisy; centroid may drift/jitter between scans — consider smoothing (rolling avg over last N scans) if visually unstable.
3. `iw scan` requires interface not already in managed/connected-only mode restrictions on some driver — verify on actual kiosk hardware, not just a dev Pi.
