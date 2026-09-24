# TODO

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

- [ ] Production server runs Ubuntu 25.04 (end-of-life, no security updates) — upgrade to 26.04 LTS
      before the web service exposes a login page

## Future

- [ ] **Web service** — web page for everyone via nginx on port 80 (LAN, plain HTTP for now; name TBD, meanwhile http://10.10.20.115/); TUI stays as local break-glass tool;
      Android app later (plan together). **Design: [docs/design/web-service.md](docs/design/web-service.md)** —
      ~5 users, viewer/operator/admin, Ionic + Angular (TypeScript), web built locally → GitHub release. It needs:
  - [x] **User login** — argon2id, 12 h bearer sessions, lockout; TUI break-glass key (phase 1)
  - [x] **Per-user activity log** — `actions_log.user/user_id` + append-only `audit_events` (phase 1)
        (`actions_log.user` exists but is always "admin"); include logins, edits, deletes, settings changes
  - [x] **Permissions** — viewer / operator / admin on every endpoint (phase 1): who can view, run commands, kill/restart,
        edit inventory, change settings, manage users
  - [x] User management — API `/api/v1/users` + `scripts/manage.sh` (web UI in phase 4)
  - [ ] Phase 0: nginx in front (installed by deploy.sh), uvicorn on 127.0.0.1
  - [ ] Enforce `must_change_password` (web page forces a change on first login)
  - [x] Decide UI stack → Ionic/Angular app in `web/`, served by nginx (API proxied to uvicorn on 127.0.0.1); released via GitHub releases
  - [ ] Live progress for health/command runs (polling vs WebSocket/SSE)
  - [ ] Feature parity with TUI: inventory, select, execute, monitor, logs, health, discovery, tasks, settings
  - [ ] Multi-worker support (if ever needed): run the scheduler in exactly one process, keep
        settings in DB/shared store instead of per-process cache — until then `--workers 1`
  - [ ] Later: HTTPS in nginx via Let's Encrypt for the chosen *.omnika.com name (DNS-01)
- [ ] **Showroom / presentation** — project showcase: what it does, screenshots/demo of TUI + web UI,
      architecture overview; demo mode with fake Pis so it can be shown without real hardware
- [ ] **Documentation** — proper docs (user guide, admin/deployment guide, API reference, developer guide);
      decide on format (wiki vs docs site, e.g. MkDocs) and keep README/wiki in sync
