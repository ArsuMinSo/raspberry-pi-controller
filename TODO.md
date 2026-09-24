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
- [ ] Apply `002_mac_pk.sql` to the live DB and run DB/API tests against `pi_controller_test`

## Deploy (`scripts/deploy.sh`)

- [ ] `curl … | sudo bash` first install: `read` for DB_PASSWORD consumes the script from stdin — use `read … < /dev/tty`
- [ ] Deploy runs every migration via `setup_db.sh` — guard before `git pull` (or add a `schema_migrations`
      table) so a failing migration doesn't leave new code pulled next to an old schema; prompt to back up DB first
- [ ] `.env` is `source`d by bash and parsed by systemd `EnvironmentFile` — passwords with `$`, spaces, quotes, `#` break or differ; quote/validate
- [ ] venv path mismatch: `deploy.sh` uses `.venv`, `systemd/pi-controller.service` uses `venv`
- [ ] git as root on `/opt/pi-controller` owned by `pi_controller` → "dubious ownership"; add `safe.directory` or run git as service user
- [ ] Consider untracking `config.yaml` (ship `config.example.yaml`) — tracked copy currently contains dev-machine values (key path, username)

## Future

- [ ] **Web service** — operate the controller from a browser, alongside the TUI.
      Backend is already a REST API, so the UI is mainly a new client, but it needs:
  - [ ] **User login** — accounts, password hashing, sessions/tokens (replaces "no auth, localhost trust")
  - [ ] **Per-user activity log** — every action attributed to the logged-in user
        (`actions_log.user` exists but is always "admin"); include logins, edits, deletes, settings changes
  - [ ] **Permissions** — roles (e.g. viewer / operator / admin): who can view, run commands, kill/restart,
        edit inventory, change settings, manage users
  - [ ] User management (create/disable users, reset passwords)
  - [ ] Decide: serve UI from FastAPI (static/templates) or a separate app
  - [ ] Live progress for health/command runs (polling vs WebSocket/SSE)
  - [ ] Feature parity with TUI: inventory, select, execute, monitor, logs, health, discovery, tasks, settings
  - [ ] HTTPS + running beyond localhost (bind address, reverse proxy)
- [ ] **Showroom / presentation** — project showcase: what it does, screenshots/demo of TUI + web UI,
      architecture overview; demo mode with fake Pis so it can be shown without real hardware
- [ ] **Documentation** — proper docs (user guide, admin/deployment guide, API reference, developer guide);
      decide on format (wiki vs docs site, e.g. MkDocs) and keep README/wiki in sync
