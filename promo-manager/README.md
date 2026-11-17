# Promo Manager

A small self-hosted admin panel for organizing partner-server promotions on Discord:
keep a list of partner communities, prepare announcements, and schedule them to
channels that those servers have approved.

## Features

- **Partner communities in one place** – each with its server ID, timezone, rules/notes
  and its own minimum gap between posts.
- **Content library** – short announcements (up to 2000 characters) with an optional
  image by URL or upload (png, jpg, gif, webp, max 8 MB).
- **Per-community schedules** – one time, every N minutes, or weekly on chosen days at a
  time of day in the community's timezone (DST aware).
- **Authorized Discord integrations only** – posts go through channel webhooks or your
  own bot application's token. User-account automation is not supported.
- **Permission control**
  - A channel must be *verified* (Discord confirms it belongs to the community's server)
    and then explicitly *authorized* by an admin before anything can be posted to it.
    This is enforced on the server for scheduled and manual posts alike.
  - Two panel roles: `admin` (everything) and `editor` (content and schedules only).
- **History** – every attempt is logged as `sent`, `failed` or `skipped`, with the HTTP
  status, error text, attempt count and Discord message ID.
- **Optional network settings** – one outbound HTTP(S) proxy, request timeout and a
  bounded retry count.

## Requirements

Node.js 22.13 or newer (uses the built-in `node:sqlite` module, which prints an
"experimental" warning on Node 22).

## Quick start

```bash
cd promo-manager
npm install
cp .env.example .env      # set ADMIN_TOKEN (and optionally EDITOR_TOKEN, DISCORD_BOT_TOKEN)
npm start
```

Open `http://127.0.0.1:8787` and sign in with the admin token.

## Workflow

1. **Communities → Add a partner community.** Enter the server ID (enable Developer Mode
   in Discord, right-click the server, *Copy Server ID*), its timezone, the minimum
   number of minutes between posts that its rules allow, and any notes.
2. **Add a channel** to the community, either:
   - a **webhook URL** created by the partner server's staff for the approved channel, or
   - a **channel ID**, if your bot was invited to that server and can post there.
3. **Verify** the channel. The panel asks Discord which server the destination belongs
   to and rejects it if that is not the community's server.
4. **Authorize** the channel once the partner's staff has approved promotions there.
   You can record who approved it. Authorization can be revoked at any time.
5. **Content → New promotion**, then **Schedules → New schedule**.
6. Watch results under **History**.

## Posting rules the server enforces

| Rule | Behaviour |
| --- | --- |
| Channel not verified or not authorized | Post is skipped and logged |
| Community paused | Post is skipped and logged |
| Community minimum interval not reached for that channel | Post is skipped and logged (also for "Post now") |
| Repeat interval shorter than the community minimum (floor: 5 minutes) | Schedule is rejected |
| One-time post more than 60 minutes late (e.g. server was down) | Skipped instead of posted late |
| Mentions | `@everyone`, role and user mentions never ping |
| Rate limit (HTTP 429) | Waits the time Discord asks for, then retries within the attempt limit |
| Other 4xx errors | Logged as failed, not retried |
| 5xx / network errors | Retried with exponential backoff within the attempt limit |

## Network settings

Under **Network** (admin only) you can set an outbound `http://` or `https://` proxy for
hosts that cannot reach Discord directly, a request timeout and the maximum attempts per
post (1–5). *Test connection* checks reachability with the saved settings. There is a
single proxy by design; the tool does not rotate addresses or work around rate limits.

## Security notes

- Webhook URLs are secrets. They are stored in the local database and never returned by
  the API or shown in the panel after saving.
- The bot token is read only from the environment.
- The panel binds to `127.0.0.1` by default. To expose it, put it behind a reverse proxy
  with TLS and keep the tokens long and random.
- Back up the `data/` directory (database and uploaded images).

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `ADMIN_TOKEN` | random per run | Full-access panel token |
| `EDITOR_TOKEN` | unset | Content/schedule-only panel token |
| `DISCORD_BOT_TOKEN` | unset | Enables bot-channel destinations |
| `HOST` / `PORT` | `127.0.0.1` / `8787` | Listen address |
| `DATA_DIR` | `./data` | Database and uploads |

## Development

```bash
npm test
```

The tests run the real API and scheduler against a local mock of the Discord REST API.

| Path | Contents |
| --- | --- |
| `src/server.js` | HTTP API, validation, access control |
| `src/scheduler.js` | Due-schedule loop, posting guard, history logging |
| `src/discord.js` | Discord REST client (webhooks, bot), retries, proxy |
| `src/schedule.js` | Timezone-aware next-run calculation |
| `src/db.js` | SQLite schema and settings |
| `public/` | Admin panel (plain HTML/CSS/JS) |

## Responsible use

Only add channels where the server's staff has agreed to your promotions, and set each
community's minimum interval to match its rules. Unsolicited advertising violates
Discord's Terms of Service and Community Guidelines.
