# Web UI Control Panel — Technical Specification (Docker-First)

This document describes a complete, no‑code technical specification to add a Web UI Control Panel and run the entire system via Docker Compose. It is intended for implementation by Codex and complements docs/IMPLEMENTATION.md.

## 1) Goal

Add a secure Web UI to observe, operate, and configure the Discord Coin Economy & Marketplace without modifying the bot directly. Everything runs under Docker Compose (Bot, API, UI, DB, Redis, Jobs, Backups, Reverse Proxy).

## 2) High‑Level Architecture (containers)

- ui: Next.js/React admin/operator dashboard
- api: Node (Express/Fastify) HTTP API for UI + ops endpoints
- bot: Discord.js v14+ (interactions, ephemeral flows)
- worker: background jobs (queues, schedulers)
- db: PostgreSQL
- cache: Redis (queues, rate limits, pub/sub)
- migrate: one‑shot DB migration/seed job
- backup: nightly DB dumps to volume (optional rclone to S3)
- reverse-proxy: Traefik or Nginx for TLS and routing (ui/api)
- admin-db-ui (optional): pgAdmin/Adminer bound to localhost

All services share one internal network; only reverse‑proxy exposes 80/443.

## 3) Authentication & Authorization

- SSO with Discord OAuth2 (scopes: identify, guilds.members.read; optional email)
- UI session via httpOnly cookie; API issues short‑lived JWT (≈15m) + refresh token
- RBAC: map Discord Guild roles → app roles: SUPERADMIN, ADMIN, OPERATOR, SUPPORT, AUDITOR
- Guild binding: restrict to configured Guild ID(s)
- Optional 2FA (TOTP) for SUPERADMIN/ADMIN

## 4) Web UI — Modules & Screens

- Dashboard: KPIs, real‑time TX feed (SSE/WebSocket), quick actions
- Users: search/view balances, streaks, badges, flags, activity; actions (adjust, freeze, badges)
- Marketplace: listings/orders tables; edit/extend/cancel; pricing tools (floors, fee bands, scarcity)
- Rewards Catalog: CRUD SKUs (Money/Rank/Cosmetic/Voucher), payload/limits/expiry/visibility/stock
- Events & Quests: configure daily rewards, trivia pools, weekly quests; schedule multipliers
- Refunds & Disputes: queue with approve/refund/force‑fulfil/partial refund; reasons + TX logs
- Reports & Exports: CSV/JSON; economy health; wash/self‑trade alerts
- Settings: guild/channel bindings, role mapping, economy config, SLAs, secrets (masked), backups

## 5) Real‑Time Updates

- Redis channels: tx.stream (all TX events), ops.alerts (failures, high‑value trades)
- api subscribes → pushes to ui via SSE/WebSocket
- bot/worker publish after DB commit (idempotent)

## 6) API Design (selected endpoints)

- Auth: /auth/discord/login, /auth/discord/callback, /auth/refresh, /auth/logout
- Users: GET /users, GET /users/:id, POST /users/:id/adjust, POST /users/:id/(un)freeze, GET /users/:id/activity
- Listings & Orders: GET /listings, POST /listings/:id/edit-price, POST /listings/:id/cancel, GET /orders, GET /orders/:id, POST /orders/:id/(force-fulfil|refund)
- Rewards & Pricing: GET/POST/PUT/DELETE /rewards, GET/PUT /pricing/config
- Quests/Events: GET/POST /quests, POST /events/(start|stop)
- Reports: GET /reports/tx, GET /reports/economy
- Streams: GET /streams/tx, GET /streams/alerts (SSE)

All write ops: CSRF (double‑submit cookie) + Idempotency‑Key header; strict input validation; rate limiting via Redis.

## 7) Security Hardening

- TLS via reverse‑proxy (Traefik with Let’s Encrypt)
- httpOnly/secure cookies; SameSite=strict; CORS locked to UI origin
- CSRF on state‑changing routes; RBAC enforced server‑side
- Secrets via Docker secrets; non‑root users; read‑only FS where possible
- Webhook HMAC verification (Minecraft voucher redemption)
- Audit trail in admin_actions

## 8) Docker & Deployment Plan

- Services: reverse‑proxy, ui, api, bot, worker, db, cache, migrate, backup, admin‑db‑ui (optional)
- Networking: single internal network; only reverse‑proxy exposes 80/443
- Healthchecks: ui/api /healthz; db pg_isready; cache redis‑cli ping; bot/worker custom 200/heartbeat
- Volumes: pg_data, redis_data (optional), backups, letsencrypt
- Env & secrets: document in README; UI uses NEXTAUTH_URL; secrets via Docker secrets

## 9) Data & Events (additions)

- AdminAction table: id, actor_id, action, subject_type/id, before/after, reason, created_at
- StreamEvents: ephemeral pub/sub only
- PricingSnapshot (optional): median/volume history for charts

## 10) Observability

- Structured JSON logs with request IDs; optional /metrics (Prometheus)
- Queue/job metrics (depth, retries); alert hooks (Discord webhooks)

## 11) README Additions (Web Panel & Docker Quickstart)

Include: prereqs; env + Docker secrets; compose up; panel login via Discord; guild binding & role mapping; create channels & hub; backups & restore; scaling; security; troubleshooting.

## 12) Acceptance Criteria

- Discord login; role mapping enforced; non‑guild blocked
- Live TX feed in UI < 2s
- Create/Edit/Cancel listings from UI → Discord shop reflects within ≈5s
- Refund/Force‑fulfil update escrow + TX atomically
- Pricing guards editable in UI and enforced by bot
- One‑command startup; no manual DB steps

## 13) Test Plan (high‑level)

- Auth/RBAC correctness; escrow integrity under failures; pricing rules enforced
- Streams at ≥100 TX/min remain responsive; backups restored cleanly; CSRF/CORS/secrets verified

