# Web Service — Design

**Status:** draft for review · **Date:** 2026-09-24

Operate the controller from a browser and a phone, next to the existing TUI, with real user accounts,
per-user activity logging and role-based permissions.

## Decisions (from review)

| Topic | Decision |
|-------|----------|
| Users | ~5 people |
| Roles | `viewer` / `operator` / `admin` |
| Client | TypeScript — **Ionic 9 + Angular 22 (standalone) + Capacitor 8**, same stack as `UTB/05_3WS/PM/02_projekt/counter-app`. One codebase → web app (served by the controller) + Android app (Capacitor) |
| Passwords | Setting / changing / resetting a password asks **3 times**, all must match (TUI, web, app, CLI) |

## Current state (what changes)

- API has **no auth**; uvicorn listens on `0.0.0.0:8000`, plain HTTP. Anyone on the LAN (or tailnet) can run commands on every Pi.
- `actions_log.user` is always `"admin"`.
- Long operations **block the HTTP request** until every Pi is done (`POST /command/execute`, `/health/trigger`,
  `/process/kill`, `/service/restart`, `/discovery/scan`) although they answer `status: "queued"`. The TUI gets
  progress by firing one request per Pi from its own thread pool. A browser/phone needs real background jobs.
- Must stay **one uvicorn worker** (scheduler + runtime settings are per-process).

## Architecture

```
 Browser ─┐                      ┌──────────────── Ubuntu server ─────────────────┐
 Android ─┼── HTTPS ──► nginx ───┤ /            → static Ionic build (web/www)    │
 TUI ─────┘   (443)              │ /api/v1/*    → uvicorn 127.0.0.1:8000 (1 worker)│
                                 └────────────────────────────────────────────────┘
```

- **nginx** terminates TLS, serves the built web app, proxies `/api/` to uvicorn. uvicorn binds to **127.0.0.1 only**.
- **API moves under `/api/v1`** (so it can't collide with web-app routes). Old root paths stay as aliases for one
  release while the TUI is updated, then are removed.
- **HTTPS certificate:** the server is on Tailscale (`100.123.70.123`) → `tailscale cert` gives a real Let's Encrypt
  certificate for `<host>.<tailnet>.ts.net`, which phones accept without extra setup. LAN-only access would need an
  internal CA installed on every device (see open question 2).
- **Repo layout:** new `web/` directory (Ionic Angular app) in this repo. `deploy.sh` builds it (`npm ci && npm run build`)
  with Node 24 LTS and copies `web/www` to where nginx serves it.

## Authentication

- **Password hashing:** argon2id (`argon2-cffi`).
- **Sessions:** opaque random token (32 bytes) returned by `POST /api/v1/auth/login`, sent as `Authorization: Bearer …`
  by all three clients. Only its SHA-256 hash is stored (`sessions` table). Revocable: logout, user disabled,
  password changed → all that user's sessions revoked.
  - Lifetime: 12 h idle / 7 days absolute (app can stay logged in for a week; web re-logs daily).
  - Why bearer everywhere instead of cookies: the Capacitor app runs on its own origin (`https://localhost`), where
    cookies are awkward; one mechanism for web, app and TUI keeps it simple. Web stores the token via
    `@capacitor/preferences` (localStorage on web) + strict Content-Security-Policy.
- **Brute-force protection:** 5 failed logins per username+IP → 15 min lockout; every failure is logged.
- **Password rules:** ≥ 12 characters; set/change/reset forms have 3 fields that must match.
- **Login itself:** password asked **once** — see open question 1.
- **First admin:** created on the server by a CLI command, not the web:
  `sudo -u pi_controller .venv/bin/python -m backend.manage create-user --role admin <username>` (password asked 3×).
  Same command resets a forgotten admin password.
- **TUI:** gets a login screen; token cached in `~/.config/pi-controller/session` (mode 600).
- **Scheduled tasks** run as the user who created/last edited them (stored on the task) — logged under that name.

## Roles & permissions

| Capability | Endpoints | viewer | operator | admin |
|------------|-----------|:------:|:--------:|:-----:|
| View inventory, Pi status, health results, action results | `GET /pi/*`, `GET /health/*`, `GET /command/*`, `GET /process/*`, `GET /service/*`, `GET /discovery/scan/*` | ✓ | ✓ | ✓ |
| View activity log | `GET /logs` | ✓ | ✓ | ✓ |
| Run health check | `POST /health/trigger` | | ✓ | ✓ |
| Kill process / restart service | `POST /process/kill`, `POST /service/restart` | | ✓ | ✓ |
| Execute arbitrary command | `POST /command/execute` | | ✓ | ✓ |
| Discovery scan (updates IP/hostname of known Pis) | `POST /discovery/scan` | | ✓ | ✓ |
| Add / edit / delete Pis | `POST /pi`, `POST /pi/bulk`, `PATCH /pi/*`, `DELETE /pi/*` | | | ✓ |
| Deploy SSH key | `POST /pi/deploy-key` | | | ✓ |
| Settings (read + write + test) | `/settings*` | | | ✓ |
| Scheduled tasks (view + manage) | `/tasks*` | | read | ✓ |
| Manage users | `/users*` | | | ✓ |
| Own account: change password, list/revoke own sessions | `/auth/*`, `/me/*` | ✓ | ✓ | ✓ |

Enforced server-side by a FastAPI dependency per route (`require_role("operator")`); clients only hide what the
user can't do. Every `403` is logged. See open question 3 on arbitrary command execution.

## Activity log

Two append-only tables, both protected by the existing "no DELETE" rule pattern:

1. **`actions_log`** (existing) — Pi operations. `user` is filled with the real username; new `user_id` column.
2. **`audit_events`** (new) — everything else:
   `id, ts, user_id, username, event, target, details JSONB, ip, user_agent`.
   Events: `login`, `login_failed`, `logout`, `password_changed`, `session_revoked`, `permission_denied`,
   `pi_created/updated/deleted`, `pi_bulk_created`, `deploy_key`, `settings_changed` (old → new values, no secrets),
   `task_created/updated/deleted`, `user_created/updated/disabled/role_changed/password_reset`.

`GET /api/v1/logs` returns both, merged by time, filterable by user / event / Pi / date. Passwords are never logged;
a command's text is logged (it already is), so commands containing secrets will be visible — same as today.

## Background jobs & live progress

- Long operations become real jobs: `POST` validates, creates the `actions_log` row (`status=queued`), submits the work
  to an in-process `ThreadPoolExecutor`, and returns immediately with `action_id`.
- Per-Pi results are written as each Pi finishes (new `action_results` table: `action_id, position, exit_code,
  stdout, stderr, error, duration_ms, finished_at`), so progress = rows done / Pis selected.
- Clients **poll** `GET /api/v1/actions/{id}` every ~1 s while running (fine for 5 users). Server-Sent Events can
  replace polling later without API changes to the rest.
- On restart, jobs still `running` are marked `interrupted`.
- The TUI switches to the same mechanism (drops its per-Pi request fan-out).

## Web / Android app (Ionic)

Screens mirror the TUI:

| Screen | Content |
|--------|---------|
| Login | username + password; server URL field in the Android app |
| Inventory | Pi list (search, status/tag filters, numeric position sort), multi-select, status colours, CPU/RAM/temp |
| Pi detail | status, hardware info, last health values, recent actions for this Pi |
| Actions | health check / kill / restart / execute on selection → progress screen with per-Pi results + full output |
| Discovery | scan range, results, add (admin) |
| Logs | merged activity log with filters |
| Scheduled tasks | list (operator read), manage (admin) |
| Settings | SSH + network settings (admin) |
| Users | list, create (password 3×), change role, disable, reset password (admin) |
| Account | change own password (3×), active sessions, logout |

- Typed API client generated from FastAPI's OpenAPI schema (`openapi-typescript`) — backend and app stay in sync.
- Android: Capacitor build with the server URL configurable at first start; reachable over Tailscale.
- Also installable as a PWA from the browser.

## Database migrations (`003_…`)

- `users (id, username UNIQUE, password_hash, role CHECK IN ('viewer','operator','admin'), is_active,
  must_change_password, created_at, updated_at, last_login_at)`
- `sessions (id, user_id, token_hash UNIQUE, created_at, last_used_at, expires_at, revoked_at, ip, user_agent)`
- `audit_events` (above) + no-delete rule
- `action_results` (above)
- `actions_log`: add `user_id`; widen `status` CHECK with `interrupted`
- `scheduled_tasks`: add `owner_user_id`

## Rollout phases

| Phase | Scope | Outcome |
|-------|-------|---------|
| 0 · Server | Ubuntu 25.04 → 26.04 LTS, nginx, Tailscale cert, uvicorn on 127.0.0.1 | HTTPS in front, API no longer open on the LAN |
| 1 · Backend auth | migration 003, users/sessions/roles, `/api/v1`, audit events, `backend.manage create-user`, TUI login | Every action attributed to a person; permissions enforced |
| 2 · Background jobs | job executor, `action_results`, polling endpoint, TUI on new mechanism | Web-ready progress |
| 3 · Web app MVP | `web/` Ionic app: login, inventory, Pi detail, health, logs, account | Read-only + health from the browser |
| 4 · Web app full | actions, discovery, tasks, settings, users | Feature parity with TUI |
| 5 · Android | Capacitor build, server URL setting | App on phones |
| 6 · Showroom & docs | demo mode with fake Pis (fake SSH executor), screenshots, user/admin guides | Presentable project |

Each phase ships on its own; tests (pytest for backend, vitest for the app) grow with it.

## Open questions

1. **Login prompt:** the 3× rule applies to setting a password. Should **login** also ask 3 times? (Recommended: no —
   a wrong login password just fails and is retried; 3× on every login would be painful on a phone.)
2. **Access path:** Tailscale only (real certs, works from phones anywhere on the tailnet), or also plain LAN
   (`10.10.20.x`) access, which needs an internal CA installed on each device?
3. **Arbitrary commands:** `operator` can run any shell command (optionally with sudo) on every Pi — effectively root.
   Keep it for operators, or admin-only with operators limited to health/kill/restart?
4. **Sessions:** 12 h idle / 7 days absolute OK?
5. **Where to build the web app:** on the server in `deploy.sh` (needs Node 24 there — recommended to start), or in
   GitHub Actions with `deploy.sh` downloading the built bundle?
