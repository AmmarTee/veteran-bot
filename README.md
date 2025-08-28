# Coin Economy & Marketplace Platform (Dockerized)

Production-ready coin economy with a Discord bot, marketplace with escrow, admin transaction feed, Web admin panel, and Minecraft integration — all running with a single Docker Compose command.

## Features

- Ephemeral player card (Discord) and coin hub
- Public marketplace with escrow, pricing guards, admin overrides
- Admin transaction feed with interactive actions and audit trail
- Web admin panel (Next.js) with Discord OAuth2 SSO and RBAC
- Background workers for jobs, pricing rollups, and leaderboards
- PostgreSQL, Redis, reverse-proxy TLS, nightly backups

## Architecture

ASCII overview:

```
          Internet
              |
        [reverse-proxy]
          /          \
     panel.example  api.example
        (ui)           (api)  <-- SSE (tx.stream), REST
          \             /
            [cache: Redis] <--- pub/sub, rate limits, BullMQ
                   |              \
               [worker]           [bot]
                   |                |
                [db: Postgres]  [Minecraft API / Webhook]
```

Services:
- reverse-proxy (Traefik/Nginx); ui (Next.js); api (Fastify/Express);
  bot (Discord.js v14+); worker (BullMQ); db (Postgres); cache (Redis);
  migrate (one-shot); backup (nightly); admin-db-ui (optional).

## Docker Quickstart

Prereqs: Docker + Docker Compose, a Discord application (bot + OAuth2).

1. Copy `.env.example` to `.env` and set required variables (Discord, DB, Redis, URLs, secrets). In production, use Docker secrets for sensitive values.
2. Bring up the stack: `docker compose up -d`
   - `migrate` runs DB migrations/seed; app services wait for success.
3. Point DNS:
   - `panel.example.com` → reverse-proxy 443 → `ui`
   - `api.example.com` → reverse-proxy 443 → `api`
4. Open `https://panel.example.com` and login with Discord.
5. Complete guild binding and role mapping in Settings.
6. Use the panel to create channels and post the Coin Hub (or run the bot setup command).

Health checks: UI/API expose `/healthz`; DB uses `pg_isready`; Redis uses `redis-cli ping`; bot/worker expose simple HTTP 200 or heartbeat scripts.

## Configuration

Set via `.env` or Docker secrets. Key vars:
- Discord: `DISCORD_TOKEN`, `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`, `GUILD_ID`
- URLs: `API_BASE_URL`, `PANEL_BASE_URL`
- Storage: `DATABASE_URL` (Postgres), `REDIS_URL`
- Auth: `JWT_SECRET`, `SESSION_SECRET`
- Minecraft: `MINECRAFT_API_URL`, `MINECRAFT_API_KEY`, `REDEMPTION_WEBHOOK_SECRET`
- Economy: `MARKET_FEE`, `PRICE_FLOOR_PCT`, `ESCROW_TIMEOUT_MIN`, `VOUCHER_TIMEOUT_H`, `LEADERBOARD_CRON`

## Web Panel & Docker Quickstart

- Prereqs:
  - Docker Engine ≥ 24, Docker Compose v2
  - Domains: `panel.example.com`, `api.example.com`
- Environment setup:
  - Copy `.env.example` → `.env`
  - Create Docker secrets for: `DISCORD_CLIENT_SECRET`, `JWT_SECRET`, `SESSION_SECRET`, `MINECRAFT_API_KEY`
  - Configure Discord OAuth redirect: `https://api.example.com/auth/discord/callback`
- First run:
  - `docker compose up -d` (runs migrations; services start after success)
  - Visit `https://panel.example.com` → Login with Discord
  - Complete Guild binding and Role mapping wizard
  - From Settings or a guided action, run “Create Channels & Hub” (invokes bot)
- Backups & restore:
  - Nightly dumps land in `/backups`; restore with `pg_restore -d coins -h db -U app <dumpfile>`
- Scaling:
  - Increase workers: `docker compose up --scale worker=2 -d`
  - Zero‑downtime deploys: roll services behind reverse‑proxy; rely on healthchecks
- Security:
  - TLS via reverse‑proxy, secrets via Docker secrets, firewall DB/Redis
- Troubleshooting:
  - OAuth redirect mismatch → check Discord app redirects
  - Healthcheck fails → verify DB/Redis and env/secrets
  - 429s → adjust route‑level rate limits, monitor Redis

## Usage

Users:
- Use the Coin Hub in Discord; interact via buttons: My Card, Shop, Quests, Claim Daily, Help.
- All responses are ephemeral (private) — balances and purchases never post publicly.

Admins:
- Operate from the Web panel: users, marketplace, rewards, events, settings.
- Review the `#coin-transactions` channel for live TX feed and take actions (refund, fulfil, cancel, freeze, note).

## Screens/Examples

- Ephemeral “My Card” embed: balance, streak, last 3 transactions.
- Listing embed in `#shop`: seller, price, qty, Buy button; admin badges.
- Web panel: dashboard KPIs, live TX feed (SSE), RBAC-guarded actions.

## Security

- TLS via reverse-proxy; httpOnly secure cookies; SameSite=strict.
- CSRF on state-changing API routes; CORS locked to the panel origin.
- Secrets via Docker secrets; containers run as non-root; least-privilege.
- Webhook HMAC verification for voucher redemption; full audit trail.

## Backups & Restore

- Nightly `pg_dump` to `/backups` volume. Example restore:
  - `pg_restore -d coins -h db -U app /backups/coins_YYYY-MM-DD_HHMM.dump`

## Scaling

- Horizontal scale on `worker` and `api`; Redis-backed queues. Deploy with zero-downtime by updating services one-by-one behind reverse-proxy.

## Troubleshooting

- OAuth redirect mismatch: verify Discord app redirect URIs match `PANEL_BASE_URL`.
- Healthcheck fails: check DB/Redis connectivity and secrets.
- 429s: tighten rate limits or adjust per-route limits; inspect Redis metrics.

## Contributing & License

- See `docs/IMPLEMENTATION.md` for the full spec and acceptance criteria.
- Contributions welcome via PR with tests aligned to the Test Plan.
