# Coin Economy + Marketplace + Web Control Panel — Implementation Instructions

This document specifies the complete, production-grade system to build. It defines scope, services, data model, APIs, UI, workers, security, Docker Compose topology, health checks, backups, acceptance criteria, and a test plan. This file contains specifications only — no source code.

## 0) Objective

Deliver a system that:

1. Boots with one command via Docker Compose (no manual DB steps).
2. Provides a Discord bot with ephemeral player flows, a player marketplace with escrow, and an admin transaction feed.
3. Exposes a Web UI admin panel for operations, audit, and configuration.
4. Integrates with Minecraft (direct API or voucher redemption).
5. Ships with a comprehensive README including Docker/Web Panel Quickstart and a runbook.

## 1) Services (Containers)

Provision the following services on a shared internal Docker network. Only the reverse-proxy exposes ports 80/443.

- reverse-proxy: Traefik (preferred) or Nginx for TLS + routing.
- ui: Next.js (React) admin panel with Discord OAuth2 SSO.
- api: Fastify/Express Node service providing HTTP API + SSE/WebSocket streams.
- bot: Discord.js v14+ bot (slash commands, buttons, ephemeral flows).
- worker: background jobs (queues, schedulers, retries) using BullMQ.
- db: PostgreSQL.
- cache: Redis (queues, rate-limit, pub/sub).
- migrate: one-shot job to run DB migrations and seed.
- backup: nightly DB dumps to a mounted volume.
- admin-db-ui (optional): pgAdmin/Adminer bound to localhost only.
- watchtower (optional): image auto-updates (disabled by default).

## 2) Environment & Secrets

Provide `.env.example`; parse `.env` and support Docker secrets in production.

Core ENV:

- DISCORD_TOKEN
- DISCORD_CLIENT_ID
- DISCORD_CLIENT_SECRET (Docker secret in prod)
- GUILD_ID
- DATABASE_URL=postgres://app:app@db:5432/coins
- REDIS_URL=redis://cache:6379/0
- JWT_SECRET (Docker secret in prod)
- SESSION_SECRET (Docker secret in prod)
- API_BASE_URL=https://api.example.com
- PANEL_BASE_URL=https://panel.example.com

Minecraft:

- MINECRAFT_API_URL (if direct fulfilment)
- MINECRAFT_API_KEY (secret)
- REDEMPTION_WEBHOOK_SECRET (HMAC for voucher webhook)

Economy Tunables:

- MARKET_FEE=0.08
- PRICE_FLOOR_PCT=0.70
- ESCROW_TIMEOUT_MIN=15
- VOUCHER_TIMEOUT_H=72
- LEADERBOARD_CRON=*/15 * * * *

## 3) Data Model (PostgreSQL)

Implement with idempotent migrations; seed defaults. Minimum tables:

- users: discord_id (PK), wallet_balance, escrow_balance, lifetime_earned, lifetime_spent, streak_days, last_daily_at, badges jsonb, flags jsonb, frozen boolean, timestamps.
- listings: listing_id uuid PK, seller_id, sku, qty, unit_price, fee_rate, min_per_buyer, max_per_buyer, expires_at, status (active|sold|cancelled|expired), timestamps, indexes (sku), (status, expires_at).
- orders: order_id uuid PK, buyer_id, escrow, fee, status (pending|fulfilled|refunded|cancelled), timestamps.
- order_lines: id bigserial PK, order_id uuid, listing_id uuid, qty, unit_price, FKs, index (order_id).
- transactions: tx_id uuid PK, type (earn|spend|list|buy|fulfil|refund|flag), actor_id, amount, reason, meta jsonb, created_at, indexes (created_at), (actor_id, created_at).
- rewards: sku PK, name, category (money|rank|cosmetic|voucher), price, fulfilment (api|voucher), payload jsonb, limits jsonb, expires_at null, visible boolean, timestamps.
- pricing_config: single row (price_floor_pct, market_fee, scarcity_target, alpha, ...).
- pricing_history (optional): id, sku, median_7d, volume_24h, created_at.
- admin_actions: id bigserial PK, actor_id, action, subject_type, subject_id, before jsonb, after jsonb, reason, created_at.
- invites/boosts/quests (minimal): track claims and cooldowns (user_id, type, last_claim_at, ...).

## 4) Core Bot Behavior (Discord.js v14+)

Channels created on first-run setup:

- #coin-hub (public; pinned hub embed with buttons)
- #leaderboard (public read-only)
- #shop (public read-only; bot posts listings)
- #coin-transactions (admin-only)

Ephemeral UX (no per-user channels):

- Hub buttons: My Card, Shop, Quests, Claim Daily, Help.
- My Card: returns ephemeral embed (balance, streak, badges, season rank, last 3 TX) with action buttons.
- Shop: category select → SKU view → confirm buy → result + receipt.
- Quests: daily trivia/quests with cooldown validation.
- Claim Daily: enforces cooldown and streak rules.

Leaderboard:

- Top 10 wallet balances; bot updates via schedule or event.
- “View Yours” button opens caller’s ephemeral card.

Admin Transaction Feed:

- Every TX event posts an embed to #coin-transactions (type, users, item/SKU, qty, price, fees, coin deltas, balances, status, tx_id, listing_id).
- Admin buttons: Refund, Cancel Listing, Force Fulfil, Freeze User, Note — all write admin_actions with reason and snapshots.

Marketplace:

- Sell flow: button → modal (price, qty, expiry, limits) → pricing guards → create listing → post in #shop → TX:list.
- Buy flow: Buy → ephemeral quote + qty modal → move coins to escrow → attempt fulfilment → release escrow on success → TX:buy + fulfil.
- Pricing guards: enforce PRICE_FLOOR_PCT against 7-day median; fee bands by undercut/over-average; scarcity multiplier.

Escrow & Idempotency:

- On buy: wallet_balance -= total; escrow_balance += total (atomic).
- On fulfil success: transfer net (after fees) from escrow to seller; fees to treasury; mark fulfilled.
- Use idempotency keys for external calls; retries safe.

## 5) API Service (Fastify/Express)

Auth & RBAC:

- Discord OAuth2 login (identify, optional guilds.members.read).
- Map Discord roles → app roles (SUPERADMIN, ADMIN, OPERATOR, SUPPORT, AUDITOR).
- Sessions via httpOnly cookies; short-lived JWT + refresh tokens.
- Block non-guild members.

Endpoints (examples):

- GET /healthz
- GET /auth/discord/login, GET /auth/discord/callback, POST /auth/logout, POST /auth/refresh
- Users: GET /users, GET /users/:id, POST /users/:id/adjust, POST /users/:id/freeze, POST /users/:id/unfreeze, GET /users/:id/activity
- Marketplace: GET /listings, POST /listings/:id/edit-price, POST /listings/:id/cancel, GET /orders, GET /orders/:id, POST /orders/:id/force-fulfil, POST /orders/:id/refund
- Rewards & Pricing: GET/POST/PUT/DELETE /rewards, GET/PUT /pricing/config
- Quests/Events: GET/POST /quests, POST /events/start, POST /events/stop
- Reports: GET /reports/tx, GET /reports/economy
- Streams: GET /streams/tx (SSE), GET /streams/alerts (SSE)

Security:

- CSRF (double-submit cookie) and Idempotency-Key on writes.
- Strict validation (zod/yup). Rate limiting (Redis) per route.

## 6) UI (Next.js)

Routes:

- /login, /
- /users, /users/:id
- /marketplace/listings, /marketplace/orders
- /rewards, /quests, /events, /reports, /settings

Components:

- Server-side paginated tables; drawers/modals; live badges for queues/failures/alerts.
- RBAC-guarded views; audit reasons for destructive actions.

## 7) Background Jobs (Worker)

Use BullMQ (Redis):

- listing:expire — minutely; expire and unlist past-due listings.
- pricing:rollup — compute metrics; write pricing_history.
- leaderboard:refresh — per LEADERBOARD_CRON.
- fulfilment:retry — exponential backoff.
- escrow:timeout — auto-refund after SLA.
- digest:daily — post daily stats to #coin-transactions and record admin_actions.

Publish events via Redis pub/sub after commits: tx.stream (transactions), ops.alerts (alerts).

## 8) Minecraft Integration

Direct API mode:

- Call panel/plugin endpoint {player_id, action, payload}; verify HMAC if supported.
- On success: mark fulfilled; on failure: retry then refund.

Voucher mode:

- Generate UUID; store pending; return redeem code; receive POST /webhooks/redeem HMAC callback; on valid redeem: mark fulfilled.

All operations idempotent via tx_id/order_id.

## 9) Security

- TLS via reverse-proxy (Traefik + Let’s Encrypt).
- httpOnly, secure cookies; SameSite=strict.
- CORS locked to panel origin.
- CSRF on state-changing API routes.
- RBAC enforced server-side.
- Secrets via Docker secrets; non-root containers; read-only FS where possible; drop capabilities.
- Webhook HMAC verification.
- Full audit trail in admin_actions.

## 10) Docker Compose Requirements

Compose services summary and requirements:

- reverse-proxy: Traefik with 80/443; ACME storage volume; routes panel.example.com → ui; api.example.com → api.
- ui: depends on api; healthcheck GET /healthz; env NEXTAUTH_URL, OAuth, API_BASE_URL.
- api: depends on db, cache; healthcheck GET /healthz validates DB/Redis; secrets mounted.
- bot: depends on db, cache, migrate (healthy/completed); health probe.
- worker: same base image as bot with different entrypoint; depends on db, cache.
- migrate: one-shot; runs migrations + seed; on failure, abort start of bot/worker.
- db (Postgres): volume pg_data; POSTGRES_INITDB_ARGS="--data-checksums"; internal only.
- cache (Redis): optional persistence; internal only.
- backup: volume /backups; nightly cron dumps via pg_dump; optional rclone push.
- admin-db-ui (optional): bind 127.0.0.1:8080 only.

Volumes: pg_data, redis_data (optional), backups, letsencrypt.

Networking: single internal network; only reverse-proxy exposes ports.

Healthchecks: Postgres (pg_isready), Redis (redis-cli ping), UI/API/Bot/Worker (HTTP probes or script exit codes).

Start order: db, cache → migrate → api, worker, bot, ui, reverse-proxy.

## 11) Logging & Observability

- JSON logs with request IDs.
- API /metrics (Prometheus): HTTP latency, errors; queue depth, job durations.
- Alerts: Discord webhook for critical errors; high-value trade pings (rate-limited).

## 12) README.md (Must Deliver)

README must include: Title & Intro; Features; Architecture diagram (ASCII OK); Docker Quickstart; Configuration; Usage; Screens/Examples; Security; Backups & Restore; Scaling; Troubleshooting; License; Contributing.

## 13) Acceptance Criteria

- docker compose up -d boots the stack; no manual DB.
- Discord login works; non-guild blocked; RBAC enforced.
- Bot creates channels; hub pinned; ephemeral flows functional with cooldowns.
- Marketplace supports list, buy, escrow, fulfil, refund; admin overrides.
- #coin-transactions shows events with admin action buttons.
- Pricing guards enforced.
- Web UI streams TX within <2s.
- Nightly backups present; restore documented.
- Security posture: TLS, CSRF, HMAC, secrets via Docker secrets; DB/Redis not publicly exposed.
- README is sufficient for another engineer to deploy unaided.

## 14) Test Plan (Minimum)

- Auth/RBAC: deny non-guild; role changes effective on next login.
- Economy: verify daily claim cooldown and streak math.
- Escrow integrity: kill worker during fulfilment → no coin loss; reconcile job fixes state.
- Marketplace rules: cannot list below floor; fee bands and per-buyer limits enforced.
- Voucher flow: redeem webhook validates HMAC; exactly-once fulfilment.
- Throughput: simulate 100 tx/min; UI stream responsive; no event loss.
- Backups/Restore: restore to new env yields consistent state.
- Security: CSRF blocks forged POST; CORS locked; secrets not logged.

