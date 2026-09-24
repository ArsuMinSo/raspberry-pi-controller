# Web Service — Design

**Status:** draft for review · **Updated:** 2026-09-24

Operate the controller from a browser, with real user accounts, per-user activity logging and role-based
permissions. The TUI stays as a local backup tool on the server.

## Decisions (from review)

| Topic | Decision |
|-------|----------|
| Users | ~5 people |
| Roles | `viewer` / `operator` / `admin` |
| Clients | **Web page** — the main way in, for everyone. **TUI** — local-only backup on the server itself (break-glass). **Android app** — out of scope for now |
| Web stack | TypeScript — **Ionic 9 + Angular 22 (standalone)**, same stack as `UTB/05_3WS/PM/02_projekt/counter-app`. Capacitor added later if/when the Android app is planned |
| Network | **LAN only** (no Tailscale), **plain HTTP** for now at `http://tv.omnika.com:8000/` (`:8080` on that host is another service). No nginx — uvicorn serves web + API |
| Passwords | Setting / changing / resetting a password asks **2 times** (entry + confirmation). **Login asks once** |
| Arbitrary commands | **Admin (web) and TUI only**, with or without `sudo` |
| Session length | **12 h maximum** from login, no separate idle timeout (log in once per working day) |
| Web build | Built on the dev machine, published as a **GitHub release**; `deploy.sh` downloads it (no Node on the server, no build output in git) |

## Current state (what changes)

- API has **no auth**; uvicorn listens on `0.0.0.0:8000`, plain HTTP. Anyone on the LAN can run commands on every Pi.
- `actions_log.user` is always `"admin"`.
- Long operations **block the HTTP request** until every Pi is done (`POST /command/execute`, `/health/trigger`,
  `/process/kill`, `/service/restart`, `/discovery/scan`) although they answer `status: "queued"`. The TUI gets
  progress by firing one request per Pi from its own thread pool. A browser needs real background jobs.
- Must stay **one uvicorn worker** (scheduler + runtime settings are per-process).

## Architecture

```
                                 ┌──────────────── Ubuntu server (tv.omnika.com) ────────────────┐
 Browser (LAN) ── HTTP :8000 ──► │ uvicorn 0.0.0.0:8000 (1 worker)                                │
                                 │   /api/v1/*  → FastAPI routes (login required)                 │
                                 │   /*         → web-current/ (static Ionic build, SPA fallback) │
                                 │        ▲                                                       │
                                 │ TUI (sudo, on the server) → 127.0.0.1:8000 + break-glass key   │
                                 └────────────────────────────────────────────────────────────────┘
```

- **One process, one port:** uvicorn serves the API under `/api/v1` and the built web page from
  `/opt/pi-controller/web-current/` (FastAPI `StaticFiles`; unknown paths fall back to `index.html` for the
  web app's own routes). No nginx, nothing extra to install on the server.
- **API moves under `/api/v1`** so it can't collide with web-page routes (e.g. `/logs`). The TUI is updated in the
  same release, so old root paths are simply removed — no aliases.
- **Name:** people open `http://tv.omnika.com:8000/`. `tv.omnika.com` must resolve to this server on the LAN
  (DNS entry or `hosts` line) — see open question 1. Port `8080` on that host belongs to another service.
- **Plain HTTP (for now):** passwords and session tokens cross the LAN unencrypted — anyone who can capture LAN
  traffic could read them. Acceptable on the isolated LAN to start; sessions end after 12 h, which limits damage.
  **Later:** `omnika.com` is a real domain, so a free Let's Encrypt certificate for `tv.omnika.com` (DNS-01
  challenge) would give HTTPS that every browser trusts, without installing anything on devices.

## Authentication

- **Password hashing:** argon2id (`argon2-cffi`).
- **Sessions:** opaque random token (32 bytes) returned by `POST /api/v1/auth/login`, sent as `Authorization: Bearer …`.
  Only its SHA-256 hash is stored (`sessions` table). Valid **12 h from login**, then log in again. Revocable: logout,
  admin revokes, user disabled, password changed → all that user's sessions end.
  Web stores the token in `sessionStorage` (cleared when the browser closes) + strict Content-Security-Policy.
  Over plain HTTP the token is visible on the network — see Architecture.
- **Brute-force protection:** 5 failed logins per username+IP → 15 min lockout; every failure is logged.
- **Password rules:** ≥ 12 characters; set/change/reset: password + confirmation (2 fields, must match). Login: one field.
- **First admin:** created on the server by a CLI command, not the web:
  `sudo -u pi_controller .venv/bin/python -m backend.manage create-user --role admin <username>` (password asked 2×).
  Same command resets a forgotten password.
- **Scheduled tasks** run as the user who created/last edited them (stored on the task) — logged under that name.

### TUI — local break-glass access

The TUI becomes a **backup tool used only on the server itself** — for when the web page or accounts are broken,
or someone is locked out.

- No username/password. `deploy.sh` generates a random **break-glass key** in `/opt/pi-controller/.tui-key`
  (owner `pi_controller`, mode 600). The TUI reads it, so it is run with `sudo` on the server.
- The TUI talks to `127.0.0.1:8000` and sends the key in a separate header. The backend accepts that header
  **only on connections from 127.0.0.1** (there is no proxy in front, so the client address is trustworthy),
  and grants `admin`.
- Every TUI action is logged as `local-tui (<unix user>)` — the TUI sends the `sudo` caller (`$SUDO_USER`).
- Works even if the users/sessions tables are empty or broken; can't be used from the network.
- Rotating the key: re-run `deploy.sh` (or `backend.manage rotate-tui-key`).

## Roles & permissions

| Capability | Endpoints | viewer | operator | admin |
|------------|-----------|:------:|:--------:|:-----:|
| View inventory, Pi status, health results, action results | `GET /pi/*`, `GET /health/*`, `GET /command/*`, `GET /process/*`, `GET /service/*`, `GET /discovery/scan/*` | ✓ | ✓ | ✓ |
| View activity log | `GET /logs` | ✓ | ✓ | ✓ |
| Run health check | `POST /health/trigger` | | ✓ | ✓ |
| Kill process / restart service | `POST /process/kill`, `POST /service/restart` | | ✓ | ✓ |
| Discovery scan (updates IP/hostname of known Pis) | `POST /discovery/scan` | | ✓ | ✓ |
| **Execute arbitrary command**, incl. `sudo` (effectively root on Pis) — also allowed from the TUI | `POST /command/execute` | | | ✓ |
| Add / edit / delete Pis | `POST /pi`, `POST /pi/bulk`, `PATCH /pi/*`, `DELETE /pi/*` | | | ✓ |
| Deploy SSH key | `POST /pi/deploy-key` | | | ✓ |
| Settings (read + write + test) | `/settings*` | | | ✓ |
| Scheduled tasks (view + manage) | `/tasks*` | | read | ✓ |
| Manage users | `/users*` | | | ✓ |
| Own account: change password, list/revoke own sessions | `/auth/*`, `/me/*` | ✓ | ✓ | ✓ |

Enforced server-side by a FastAPI dependency per route (`require_role("operator")`); the web page only hides what
the user can't do. Every `403` is logged.

## Activity log

Two append-only tables, both protected by the existing "no DELETE" rule pattern:

1. **`actions_log`** (existing) — Pi operations. `user` is filled with the real username (or `local-tui (…)`);
   new `user_id` column.
2. **`audit_events`** (new) — everything else:
   `id, ts, user_id, username, event, target, details JSONB, ip, user_agent`.
   Events: `login`, `login_failed`, `logout`, `password_changed`, `session_revoked`, `permission_denied`,
   `pi_created/updated/deleted`, `pi_bulk_created`, `deploy_key`, `settings_changed` (old → new values, no secrets),
   `task_created/updated/deleted`, `user_created/updated/disabled/role_changed/password_reset`, `tui_key_rotated`.

`GET /api/v1/logs` returns both, merged by time, filterable by user / event / Pi / date. Passwords are never logged;
a command's text is logged (it already is), so commands containing secrets will be visible — same as today.

## Background jobs & live progress

- Long operations become real jobs: `POST` validates, creates the `actions_log` row (`status=queued`), submits the work
  to an in-process `ThreadPoolExecutor`, and returns immediately with `action_id`.
- Per-Pi results are written as each Pi finishes (new `action_results` table: `action_id, position, exit_code,
  stdout, stderr, error, duration_ms, finished_at`), so progress = rows done / Pis selected.
- The web page **polls** `GET /api/v1/actions/{id}` every ~1 s while running (fine for 5 users). Server-Sent Events
  can replace polling later without other API changes.
- On restart, jobs still `running` are marked `interrupted`.
- The TUI switches to the same mechanism (drops its per-Pi request fan-out).

## Web page (Ionic)

Screens mirror the TUI:

| Screen | Content |
|--------|---------|
| Login | username + password |
| Inventory | Pi list (search, status/tag filters, numeric position sort), multi-select, status colours, CPU/RAM/temp |
| Pi detail | status, hardware info, last health values, recent actions for this Pi |
| Actions | health check / kill / restart (operator), execute (admin) on selection → progress with per-Pi results + full output |
| Discovery | scan range, results, add (admin) |
| Logs | merged activity log with filters |
| Scheduled tasks | list (operator read), manage (admin) |
| Settings | SSH + network settings (admin) |
| Users | list, create (password 2×), change role, disable, reset password, revoke sessions (admin) |
| Account | change own password (2×), active sessions, logout |

- Typed API client generated from FastAPI's OpenAPI schema (`openapi-typescript`) — backend and web stay in sync.
- Source in `web/` in this repo; build output (`web/www`) is gitignored.

## Web release & deploy (GitHub releases)

**Dev machine** — `bash scripts/release_web.sh`:
1. Refuses unless the working tree is clean and the commit is pushed (every release matches a real commit).
2. `npm ci && npm run build` in `web/`.
3. Packs `web-<commit>.tar.gz` + `.sha256`.
4. `gh release create web-<date>-<commit> --target <commit>` with both files attached.

**Server** — `deploy.sh`, after updating the code:
1. Picks the **newest web release whose commit is contained in the deployed code** — the web page is never newer
   than the backend it talks to.
2. Downloads with `curl` (public repo, no token), verifies the checksum, unpacks to
   `/opt/pi-controller/web-releases/<tag>/`.
3. Switches the `web-current` symlink atomically (the backend never serves half-copied files); keeps the last 3 for rollback.
4. If GitHub is unreachable, keeps the current web page and finishes the deploy.

If the repo is ever made private, the server needs a read-only GitHub token for step 2.

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
| 0 · Server (optional, separate) | Ubuntu 25.04 → 26.04 LTS — done together: commands pasted into the server pane, DB backup first | Server gets security updates again |
| 1 · Backend auth | migration 003, users/sessions/roles, `/api/v1`, audit events, `backend.manage`, TUI break-glass key | Every action attributed to a person; permissions enforced |
| 2 · Background jobs | job executor, `action_results`, polling endpoint, TUI on new mechanism | Web-ready progress |
| 3 · Web page MVP | `web/` Ionic app: login, inventory, Pi detail, health, logs, account; backend serves it; `release_web.sh` + deploy download | Read-only + health at `http://tv.omnika.com:8000/` |
| 4 · Web page full | actions, discovery, tasks, settings, users | Everything the TUI can do |
| 5 · Showroom & docs | demo mode with fake Pis (fake SSH executor), screenshots, user/admin guides | Presentable project |
| later · HTTPS | Let's Encrypt certificate for `tv.omnika.com` (DNS-01) | Encrypted logins, no device setup |
| later · Android | Capacitor app — **to be planned together** when needed | App on phones |

Each phase ships on its own; tests (pytest for backend, vitest for web) grow with it.

## Open questions

1. **`tv.omnika.com` → this server:** does the name already resolve to the controller on the LAN (internal DNS),
   or does it still need a DNS record? Check from a LAN machine: `getent hosts tv.omnika.com` should print the
   controller's LAN IP.
