# TODO

## Floor map — privacy/legal review (`plan_floor_map.md`)

- [ ] **BLE scan = passive collection of bystanders' device MAC + name** (`ble_scans` table, `backend/services/floor_map.py`).
      MAC address is a persistent identifier capable of tracking a device's position/movement over time — likely
      counts as personal data under GDPR (Art. 4(1)) even with no other info attached, especially since a floor
      map is explicitly a presence/location record. Not legal advice — get a real compliance check before this
      is used anywhere with non-staff foot traffic.
- [ ] `actions_log`/`action_results` is append-only (no deletes, locked decision) but now also carries raw
      BLE scan output — conflicts with GDPR right-to-erasure if a bystander's device data ever needs removing.
      Decide: exclude BLE stdout from the audit log, or accept the conflict knowingly.
- [ ] No retention/pruning exists anywhere in the codebase (`health_samples`, `wifi_scans`, `ble_scans` all grow
      forever). Add a retention job, at minimum for `ble_scans`.
- [ ] Consider hashing `device_mac` instead of storing it raw, and dropping `device_name` entirely — keeps
      "same device seen again" without storing the identifying info directly.
- [ ] `setcap cap_net_raw,cap_net_admin+eip /usr/sbin/iw` (provisioning step) grants that capability to
      **any user/process on the kiosk**, not scoped to the controller's SSH session — accepted tradeoff vs.
      passwordless sudo, but worth remembering if a kiosk is ever compromised.
- [x] Pi<->Pi BLE sightings (a Pi seeing another Pi's own Bluetooth controller MAC, `raspberries.ble_mac`) are
      exempt from the bystander-privacy concern above — it's our own fleet hardware, not a stranger's device —
      and are now used as a fallback position signal (`compute_pi_position_via_ble`) when no WiFi position
      exists yet. Ambient (non-Pi) BLE devices are unaffected, still logged/not-plotted/not-positioned.

## Review fixes — MAC as primary key (commits 77cd008..0ca4512)

- [x] **Migration 002**: bring DB in line with `backend/models.py` — drop `id`, `PRIMARY KEY (mac)`,
      widen `position` to VARCHAR(20), lowercase MACs, add `cpu_*`/`mem_percent`/`temp_c` columns and
      `scheduled_tasks` table (both exist in the model but in no migration). Abort if placeholder or
      duplicate MACs remain.
- [x] Run all migrations in order from `scripts/setup_db.sh` and `tests/conftest.py`
- [x] Discovery bulk add: skip Pis with no MAC instead of sending the all-zeros placeholder (currently 422s the whole batch)
- [x] Health check + discovery scan: check for MAC conflict before reassigning `pi.mac` (one clash aborts the whole commit)
- [x] `tests/test_database.py`: replace `test_pi_mac_allows_duplicates` with a MAC-uniqueness test
- [x] Remove `MAC_PLACEHOLDER` handling once migration guarantees no placeholder rows
- [ ] Normalise positions (`"7"` vs `"007"` vs `"00-007"`) — decide rule
- [x] Home grid: numeric-aware sort for positions (`"9"` before `"10"`)
- [x] Docs: CLAUDE.md, README
- [x] Docs: wiki (Database Schema, API Reference, TUI Guide, Installation, Development)
- [x] Apply `002_mac_pk.sql` to the live DB and run DB/API tests against `pi_controller_test` (37 passed on prod server, 2026-09-24)

## Deploy (`scripts/deploy.sh`)

- [x] `curl … | sudo bash` first install: `read` for DB_PASSWORD consumes the script from stdin — use `read … < /dev/tty`
- [x] Deploy runs every migration via `setup_db.sh` — guard before `git pull` (or add a `schema_migrations`
      table) so a failing migration doesn't leave new code pulled next to an old schema; prompt to back up DB first
- [x] `.env` is `source`d by bash (now written single-quoted, `'` rejected; backend URL escapes password) and parsed by systemd `EnvironmentFile` — passwords with `$`, spaces, quotes, `#` break or differ; quote/validate
- [x] venv path mismatch: `deploy.sh` uses `.venv`, `systemd/pi-controller.service` uses `venv`
- [x] git as root on `/opt/pi-controller` owned by `pi_controller` → "dubious ownership"; add `safe.directory` or run git as service user
- [x] Untrack `config.yaml` (ship `config.example.yaml`) — tracked copy currently contains dev-machine values (key path, username)
- [x] Password prompts ask 3 times, all must match (apply to every future password set/verify — web users too)
- [x] setup_db.sh: migrations failed with "Peer authentication failed" (socket as root) — now TCP + password

## Repo hygiene

- [x] Prune old DB backups and `config.yaml.bak-*` (newest 10 kept)
- [x] `test_logs_filter_by_position` cleanup deletes an `actions_log` row — the append-only DB rule blocks it
      (SAWarning "expected to delete 1 row(s); 0 were matched"); drop the delete from the test
- [x] Silence pytest-asyncio deprecation: set `asyncio_default_fixture_loop_scope = "function"` (pytest config)
- [ ] Line endings are mixed (most `.py` CRLF, some LF, `.gitignore` mixed). Add `.gitattributes`
      (`* text=auto eol=lf`, `*.sh eol=lf`) and renormalise in one dedicated commit — `.sh` must be LF to run

## Server

- [ ] ⏸ Postponed (2026-09-24): production server runs Ubuntu 25.04 (end-of-life, no security updates) — upgrade to 26.04 LTS
      before the web service exposes a login page

## Fleet API ideas (roles: viewer / operator / admin; long ones as background jobs)

**First picks** — cheap on the job system, cover most kiosk incidents:
- [x] `POST /pi/reboot` (operator) — no sudo (logind/polkit); web verifies via uptime
- [x] `POST /diagnostics` (operator) — throttling/under-voltage flags + disk (sysfs, no video group needed)
- [x] `GET /fleet/summary` (viewer) — counts, stale, top temp/CPU/RAM; summary strip in web
- ~~Display on/off~~ — not needed (decided 2026-09-24)

**Later:**
- [ ] `POST /pi/shutdown` (admin); `POST /pi/wake` WoL (operator, Pi 4/5 mostly unsupported)
- [ ] `GET /pi/{pos}/screenshot` (viewer) — what's on screen (`grim`/`scrot`)
- [ ] `POST /kiosk/reload` (operator), `POST /kiosk/url` (admin)
- [ ] `GET /service/status?name=` (viewer) — `systemctl is-active` across selection
- [ ] `GET /pi/{pos}/journal?unit=&lines=`, `/processes`, `/network` (viewer)
- [ ] `POST /pi/ping` (operator) — quick reachability
- [ ] `GET /pi/stale?hours=`; `GET /pi/{pos}/history` (needs `health_samples` table)
- [ ] Bulk `PATCH /pi/tags` (admin); CSV `GET /pi/export` / `POST /pi/import`
- [ ] `POST /pi/time-sync` (operator) — see `scripts/ntp-sync.txt`
- [ ] ⚠ `POST /pi/apt-upgrade`, `POST /pi/file` (admin) — conflict with locked "No deployments"; decide first
- [ ] `/alerts/rules` (admin, v2) — temp > 75 °C, unreachable > 30 min, throttling

## Future

- [ ] **Web service** — web page for everyone at http://tv.omnika.home/ (nginx, LAN, plain HTTP); TUI stays as local break-glass tool;
      Android app later (plan together). **Design: [docs/design/web-service.md](docs/design/web-service.md)** —
      ~5 users, viewer/operator/admin, Ionic + Angular (TypeScript), web built locally → GitHub release. It needs:
  - [x] **User login** — argon2id, 12 h bearer sessions, lockout; TUI break-glass key (phase 1)
  - [x] **Per-user activity log** — `actions_log.user/user_id` + append-only `audit_events` (phase 1)
        (`actions_log.user` exists but is always "admin"); include logins, edits, deletes, settings changes
  - [x] **Permissions** — viewer / operator / admin on every endpoint (phase 1): who can view, run commands, kill/restart,
        edit inventory, change settings, manage users
  - [x] User management — API `/api/v1/users` + `scripts/manage.sh` (web UI in phase 4)
  - [x] Phase 0: nginx in front (installed by deploy.sh), uvicorn on 127.0.0.1
  - [x] Enforce `must_change_password` (web page forces Account first — phase 3)
  - [x] Decide UI stack → Ionic/Angular app in `web/`, served by nginx (API proxied to uvicorn on 127.0.0.1); released via GitHub releases
  - [x] Live progress — background jobs + `GET /api/v1/actions/{id}` polling, per-Pi `action_results` (phase 2)
  - [x] Phase 3 web MVP: login, inventory, Pi detail, health + live progress, logs, account; release_web.sh + deploy download
  - [x] Phase 4a — web Users screen (admin)
  - [ ] Phase 4b — web parity with TUI (new pages/tabs):
    - [ ] **Execution** page (admin): command on selected Pis, per-Pi output, history re-run
    - [ ] **Sudo execution** (admin): Pis' `vyroba` has no passwordless sudo → sudo password entered per run
          (`sudo -S`, never stored/logged), or a sudoers rule — decide
    - [ ] Kill process / restart service (operator)
    - [ ] **Scheduled tasks** page: list (operator), create/edit/enable/delete (admin), last run + status
    - [ ] **Manage Pis** (admin): add, edit (position, MAC, tags, IP), delete; discovery scan + add found Pis;
          deploy SSH key
    - [ ] Settings page (admin): SSH + network settings
    - [ ] Inventory: **sortable columns** (click header; position, hostname, IP, status, CPU, RAM, temp, last seen)
    - [ ] Inventory: **filters** — tags, Pi version, stale, high temp / CPU / RAM, alongside status + search
    - [ ] **Dashboards**: fleet overview page (charts: reachable over time, temps, disk), per-Pi history
          (needs `health_samples` table)
  - [x] Web: retry polling on transient network errors
  - [ ] First real web release (`scripts/release_web.sh`) + browser test against the server (CSP, login, progress)
  - [ ] Multi-worker support (if ever needed): run the scheduler in exactly one process, keep
        settings in DB/shared store instead of per-process cache — until then `--workers 1`
  - [ ] Later, optional: HTTPS — `.home` isn't public, so own CA + cert in nginx, CA installed on each device
- [ ] **Showroom / presentation** — project showcase: what it does, screenshots/demo of TUI + web UI,
      architecture overview; demo mode with fake Pis so it can be shown without real hardware
- [ ] **Documentation** — proper docs (user guide, admin/deployment guide, API reference, developer guide);
      decide on format (wiki vs docs site, e.g. MkDocs) and keep README/wiki in sync
