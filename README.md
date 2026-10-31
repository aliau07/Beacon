# Beacon

Beacon is a small incident and on-call platform built with Django 5.2. Monitoring tools send
events to an HTTP API; Beacon groups them into incidents, pages whoever is on call by email and in an in-app inbox,
escalates when nobody acknowledges, shows customers a public status page and helps the team write postmortems.

## Features

- **Teams** with three roles: *owners* run the team, *admins* manage its setup (services, API keys, schedules,
  escalation policies, status page), *responders* handle incidents. Everyone has a profile time zone and an avatar,
  and times are shown in their own time zone.
- **Services** with **API keys**. A key is shown once when it is created; Beacon stores only its prefix and a
  SHA-256 hash.
- **Events API** (`POST /api/v1/events/`): trigger, acknowledge and resolve incidents. It uses
  `Authorization: Bearer <key>` auth, a fixed-window rate limit per key (configured in `.env`, answering 429 with
  `Retry-After`) and JSON 400 errors.
- **Deduplication**: one open incident per service and `dedup_key`, enforced by a partial `UniqueConstraint`.
  Two simultaneous triggers can't open two incidents: the loser's `IntegrityError` is caught and its event joins
  the winner's incident.
- **Incident states**: triggered → acknowledged → resolved, or triggered → resolved; every other move is rejected.
  Every change, page, escalation and note goes on the incident timeline.
- **Escalation policies**: ordered levels, each paging a person or whoever is on call for a schedule, with a delay.
  The whole policy can repeat N times. `manage.py run_escalations` pages the next level for unacknowledged
  incidents using `SELECT ... FOR UPDATE SKIP LOCKED`, so several workers can run safely.
- **On-call schedules**: rotations with participants, a shift length, a handoff time and an IANA time zone
  (`zoneinfo`). Handoffs stay at local clock time across daylight saving changes. Overrides always win.
  `who_is_on_call(schedule, at)` answers who is on call at any moment.
- **Paging** by email (console backend by default) plus an in-app inbox with an unread count in the navbar.
- **Public status page** per team: each component shows the worst open severity of its linked services, unless an
  admin sets a manual override. The page refreshes itself every 30 seconds with `fetch`.
- **Postmortems** for resolved incidents: the timeline and impact are filled in automatically, then the team adds
  the root cause, action items and screenshots (resized with Pillow, EXIF metadata stripped).

## Stack

Django 5.2 LTS, Bootstrap 5.3, Pillow, python-decouple, psycopg 3 and dj-database-url. It uses SQLite by default
and Postgres when `DATABASE_URL` is set. There is no DRF, Celery or Redis: the API is a plain Django view, the rate
limiter is a database counter, and escalation runs from a management command (cron).

Python 3.11 or newer.

## Getting started

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env                 # then set SECRET_KEY:
python -c "import secrets; print(secrets.token_urlsafe(50))"

python manage.py migrate
python manage.py seed_demo_data      # prints demo passwords and API keys
python manage.py runserver
```

Open http://127.0.0.1:8000/ and log in as `ada` (team owner) with the password printed by `seed_demo_data`. The
demo also includes `grace` (admin), `linus` and `margaret` (responders) and `admin` (Django admin superuser). It
creates services with API keys, two schedules (weekly Dublin handoffs, daily New York handoffs), an override, an
escalation policy, one incident in each state, a postmortem and a public status page at
http://127.0.0.1:8000/status/demo-ops/.

Passwords are generated on every run (set `DEMO_PASSWORD` to choose one). API keys can't be shown twice, so each
run revokes the previous demo keys and prints new ones. `--reset` deletes the demo team and rebuilds it.

### Escalations

Escalation needs a periodic runner. In production, run it every minute from cron:

```cron
* * * * * cd /srv/beacon && .venv/bin/python manage.py run_escalations
```

During development, keep it running in a second terminal:

```bash
python manage.py run_escalations --interval 30
```

Level 1 is paged as soon as an incident triggers. Each later level is paged when the previous level's delay passes
without an acknowledgement.

### Postgres

```bash
export DATABASE_URL=postgres://beacon:secret@localhost:5432/beacon
python manage.py migrate
```

Any URL that dj-database-url understands works. `DB_CONN_MAX_AGE` (default 60 seconds) controls persistent
connections.

### Configuration (.env)

| Setting | Default | Meaning |
| --- | --- | --- |
| `SECRET_KEY` | (required) | Django secret key |
| `DEBUG` | `False` | Development mode |
| `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` | `127.0.0.1,localhost` | Host names |
| `DATABASE_URL` | unset (SQLite) | e.g. `postgres://user:pass@host:5432/db` |
| `TIME_ZONE` | `UTC` | Server time zone; people see their own profile time zone |
| `SITE_URL` | `http://127.0.0.1:8000` | Used for links in paging emails |
| `EMAIL_BACKEND` | console | Paging emails print to the console unless you configure SMTP |
| `EVENTS_RATE_LIMIT` | `120` | Requests allowed per API key per window |
| `EVENTS_RATE_LIMIT_WINDOW` | `60` | Window length in seconds |

## Events API

`POST /api/v1/events/` with a JSON object and the service's API key:

| Field | Type | Required |
| --- | --- | --- |
| `event_action` | `"trigger"`, `"acknowledge"` or `"resolve"` | always |
| `dedup_key` | string, up to 255 characters | to acknowledge or resolve; on trigger a key is generated if missing |
| `summary` | string, up to 255 characters | to trigger |
| `severity` | `"critical"`, `"error"`, `"warning"` or `"info"` | to trigger |
| `details` | object, shown on the incident | no |

The key goes in the `Authorization` header as `Bearer <key>` (`Token <key>` also works).

```bash
export BEACON=http://127.0.0.1:8000
export BEACON_KEY=bcn_1a2b3c4d_...    # printed by seed_demo_data or shown once on the service page

# Trigger (or group into the open incident with the same dedup_key)
curl -i -X POST $BEACON/api/v1/events/ \
  -H "Authorization: Bearer $BEACON_KEY" \
  -H "Content-Type: application/json" \
  -d '{"event_action": "trigger", "dedup_key": "disk-full-db1",
       "summary": "Disk 95% full on db1", "severity": "critical",
       "details": {"host": "db1", "mount": "/var/lib/postgresql"}}'

# Acknowledge: stops the escalation
curl -X POST $BEACON/api/v1/events/ -H "Authorization: Bearer $BEACON_KEY" \
  -H "Content-Type: application/json" \
  -d '{"event_action": "acknowledge", "dedup_key": "disk-full-db1"}'

# Resolve
curl -X POST $BEACON/api/v1/events/ -H "Authorization: Bearer $BEACON_KEY" \
  -H "Content-Type: application/json" \
  -d '{"event_action": "resolve", "dedup_key": "disk-full-db1"}'
```

A successful call returns `202 Accepted`:

```json
{"status": "success", "outcome": "triggered", "message": "Incident triggered.",
 "dedup_key": "disk-full-db1", "incident_id": 12, "incident_status": "triggered"}
```

`outcome` is one of:

- `triggered`: a new incident was opened.
- `deduplicated`: a repeat of an open incident; it increments the incident's alert count.
- `acknowledged` or `resolved`: the incident changed state.
- `ignored`: nothing to do. Either no open incident has this `dedup_key`, or the move isn't allowed (for example,
  acknowledging an incident that is already acknowledged). `message` explains which.

A trigger for an acknowledged incident groups into it and leaves it acknowledged. A trigger after a resolve opens a
new incident.

Errors are JSON too:

| Status | When | Example body |
| --- | --- | --- |
| 400 | Body isn't JSON | `{"status": "error", "error": "Request body must be valid JSON."}` |
| 400 | Invalid fields | `{"status": "error", "error": "Invalid event.", "errors": {"severity": "Must be one of: critical, error, warning, info."}}` |
| 401 | Missing, unknown or revoked key | `{"status": "error", "error": "Missing, unknown or revoked API key. ..."}` |
| 405 | Not a POST | `{"status": "error", "error": "Use POST."}` |
| 413 | Body over 64 KB | `{"status": "error", "error": "Request body is larger than 65536 bytes."}` |
| 429 | Rate limit exceeded | `{"status": "error", "error": "Rate limit exceeded: 120 requests per 60 seconds ..."}` |

Every authenticated response includes `X-RateLimit-Limit` and `X-RateLimit-Remaining`; a 429 also includes
`Retry-After` (seconds until the next window). Windows are fixed: they start at multiples of
`EVENTS_RATE_LIMIT_WINDOW` seconds, and each key has its own counter.

```bash
# See the rate limiter at work (with EVENTS_RATE_LIMIT=2 in .env):
for i in 1 2 3; do
  curl -s -o /dev/null -w "%{http_code} retry-after=%header{retry-after}\n" -X POST $BEACON/api/v1/events/ \
    -H "Authorization: Bearer $BEACON_KEY" -H "Content-Type: application/json" \
    -d '{"event_action": "trigger", "dedup_key": "rl", "summary": "Rate limit demo", "severity": "info"}'
done
```

## How it works

### Apps

Each feature is its own app under `apps/`. Business rules live in each app's `services.py` and raise domain errors
(`IncidentError`, `OnCallError`, `EscalationError`, ...); permission failures raise `TeamPermissionDenied` (a 403).
Views stay thin. Apps react to each other through signals that are sent with `transaction.on_commit`, and every
email goes through `apps.core.notifications.notify()`.

| App | Responsibility |
| --- | --- |
| `core` | Base templates, `notify()`, image processing, time zone validation and middleware, severity choices |
| `accounts` | Custom user (time zone, avatar), sign-up, login, profile |
| `teams` | Teams, memberships and roles; `require_role()` and the team-scoped lookup helpers every app uses |
| `services` | Services and their API keys |
| `alerts` | The events API, payload validation, the rate limiter and the log of received events |
| `incidents` | Incident state machine, deduplication, timeline; sends `incident_triggered/acknowledged/resolved` |
| `oncall` | Schedules, rotations, overrides, `who_is_on_call()` |
| `escalation` | Policies and levels; starts on `incident_triggered`, stops on acknowledge or resolve; `run_escalations` |
| `notifications` | Pages (email plus inbox), the unread badge, "resolved" updates for everyone who was paged |
| `statuspage` | Public status pages and components |
| `postmortems` | Postmortems, timeline, action items, screenshots |
| `demo` | `seed_demo_data` |

### Design notes

- **Handoffs across daylight saving time.** A rotation's handoff is `handoff_time` on its own local clock
  (`datetime.combine(day, handoff_time, tzinfo=ZoneInfo(tz))`), converted to UTC. A 09:00 New York handoff is 14:00
  UTC in winter and 13:00 UTC in summer, and the shift that spans the change is 23 or 25 hours long. All
  comparisons are done in UTC: Python compares datetimes that share a tzinfo by wall clock, which goes wrong in the
  hour that repeats when the clocks go back. A handoff time skipped when the clocks go forward is read on the old
  offset.
- **Deduplication race.** `trigger()` looks for an open incident first. If two requests both find none, both
  insert; the partial unique index (`service`, `dedup_key` where status is open) rejects the second, which then
  records its event on the winner. On Postgres a threaded test proves this.
- **Escalation runner.** Each due incident is handled in its own transaction:
  `select_for_update(skip_locked=True, of=('self',))` locks just that escalation row, so a second worker moves on
  to another incident instead of waiting or paging twice. The incident row is then locked and its status re-read,
  so an acknowledgement that lands at the same moment always wins.
- **API keys** look like `bcn_1a2b3c4d_<43 random characters>`. Only the prefix (`bcn_1a2b3c4d`, to tell keys
  apart) and the SHA-256 hex digest of the whole key are stored.
- **Uploads** (avatars, screenshots) are decoded and re-encoded with Pillow. EXIF orientation is applied first, so
  pictures stay upright, then all metadata is dropped. JPEGs stay JPEG; other formats become PNG.

## Tests

```bash
python manage.py test                                               # SQLite
DATABASE_URL=postgres://beacon:secret@localhost:5432/beacon python manage.py test
```

There are 186 tests. They cover DST handoffs (New York and Dublin, the repeated and skipped hours), overrides and
layers, escalation timing with a mocked `timezone.now`, repeats, the deduplication race, rate limits, API auth and
validation, the state rules, permissions, uploads and the demo seed. Two of them need real concurrent transactions
(the threaded deduplication race and `SKIP LOCKED`), so they run only on Postgres and are skipped on SQLite.

## Project layout

```
config/            settings, URLs, WSGI/ASGI
apps/<app>/        models.py, services.py (rules), views.py (thin), forms.py, urls.py, admin.py,
                   templates/<app>/, tests.py
apps/core/tests/factories.py   test builders shared by every app
```
