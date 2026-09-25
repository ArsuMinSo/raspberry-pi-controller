# Changelog

All notable changes to Pi Controller, newest first. Dates are when the work landed.

## 2026-09-25

- **Scheduled tasks page** (web, admin) — list, create/edit/delete, enable toggle
- **Execute command page** (web, admin) — select Pis, run commands
- **Settings page** (web, admin) — SSH/network config, test connection
- **Sortable columns** on inventory (click headers, position/IP numeric-aware)

## 2026-09-24

- **Fleet endpoints** — reboot (no sudo, via logind), diagnostics (throttling/power/disk), fleet summary
- **Fleet summary, diagnostics, reboot with verification** (web)
- **Users screen** (web, admin) — create, role, disable, reset password, end sessions
- **Web page MVP** (phase 3) — Ionic + Angular app, login, inventory, Pi detail, health check, activity log, account
- **Background jobs** with per-Pi progress (web service phase 2)
- **Users, roles, sessions, audit trail** (web service phase 1) — argon2id, 12h bearer sessions
- **nginx in front** (phase 0) — port 80, web root + API proxy, uvicorn on 127.0.0.1
- Tracked migrations with backup + rollback, 3x password prompt on deploy
- `scripts/run_tests.sh`; tests safe to run on the production server
- TUI: require Textual ≥ 8, fixed MarkupError / stylesheet errors on newer Textual

## 2026-08-05

- **MAC is now the primary key**; position is a renameable plain number (1–10 digits) or legacy `XX-XXX`

## 2026-07-14 to 2026-07-16

- **Scheduled tasks** (TUI) — cron-based command/health/discovery via APScheduler
- Multiline command input (TextArea + Ctrl+Enter), custom SSH user/password auth
- Pi time + uptime collection (single `uptime` SSH call), shown on Home
- Sorting on Execute's Stdout/Stderr columns; Logs filter by Home selection with load-more
- Settings screen gains parallel-execution limit, retry count/delay
- Discovery matches existing Pi by MAC first, then IP (fixes stale IP after DHCP reassignment)

## 2026-07-01 to 2026-07-02

- **Sudo execution** (TUI) — toggle + optional password, solved via temp script file
- Parallel health checks (up to 10 concurrent) with live progress bar
- Detach checkbox for fire-and-forget commands (reboot, shutdown, etc.)
- Health simplified to CPU load avg %, RAM%, temp; ping before SSH to skip dead hosts

## 2026-06-18 to 2026-06-19

- **Textual TUI frontend** (replaces PyRatatui)
- Pi CRUD (create/edit/delete) via backend API and TUI modal
- Discovery screen — subnet/IP-range scan, SSH probe, bulk add with MAC dedup, deploy-key (password auth)
- Runtime SSH key path / settings override via `/settings`, persisted to `config.yaml`
- Parallel SSH execution and health checks via `ThreadPoolExecutor`
- Column sorting (click header, ▲▼ indicator) on Home and Discovery

## 2026-06-01 to 2026-06-03

- **Backend foundation**: FastAPI app, SQLAlchemy models (`raspberries`, `actions_log`), Pydantic schemas
- SSH executor with retry logic and auth handling; health check service (CPU/mem/disk via SSH)
- Subnet discovery — ARP MAC lookup + SSH probing
- Routes: inventory, health check, command execution, process kill, service restart, audit log, discovery
- Test suite: DB constraints, append-only rule, SSH executor unit tests, full API integration tests
- systemd service unit + idempotent DB bootstrap script

## 2026-05-14

- Initial commit
