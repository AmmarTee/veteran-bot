# Legocraft Coin Economy — For Humans (Docker 1‑click)

A friendly, everything‑in‑one stack:
- Web panel (Next.js)
- API (Fastify + Postgres via Prisma)
- Discord bot (discord.js)

Use it to run a coin economy in your Discord server, list items on a marketplace, and (optionally) connect to Minecraft.

## Quick Start (5 minutes)

Prerequisites
- Docker + Docker Compose
- Discord Developer Portal access

1) Clone and set env
- Copy `.env.example` → `.env`
- Fill these first:
  - `DISCORD_TOKEN` (Bot token)
  - `DISCORD_CLIENT_ID` and `DISCORD_CLIENT_SECRET`
  - `GUILD_ID` (your Discord server ID)
  - `MAIN_CHANNEL_ID` (channel to post “bot is online”)
  - `NEXTAUTH_URL` = your panel URL, e.g. `https://duckpanel.trostrum.com`
  - `NEXTAUTH_SECRET` = random string (64+ chars)
  - `PANEL_BASE_URL=https://duckpanel.trostrum.com`
  - `API_BASE_URL=https://duckapi.trostrum.com`

2) Discord app setup (once)
- Create app → add a Bot → copy the token.
- Enable “Server Members” and “Message Content” intents.
- OAuth2 → URL Generator:
  - Scopes: `bot`, `applications.commands`
  - Permissions: Send Messages, Read Message History, Embed Links
- Invite the bot with the generated URL.
- Add OAuth Redirect URI: `https://duckpanel.trostrum.com/api/auth/callback/discord`

3) Run it
- `docker compose build --no-cache && docker compose up -d`
- Check health:
  - UI: `http://localhost:3000/healthz` ⇒ 200
  - API: `http://localhost:8080/healthz` ⇒ 200
- The bot posts “✅ Bot is online and ready!” in `MAIN_CHANNEL_ID`.

4) Open the panel
- Visit `https://duckpanel.trostrum.com`
- Login with Discord
- Use the top nav: Users, Listings, Orders, Rewards, Quests, Events, Reports, Settings

Tip: If running behind Cloudflare, keep the compose ports (`3000`, `8080`) open locally and map your DNS records to the host. `NEXTAUTH_URL` must match your public panel hostname.

## What’s Included

- UI (Next.js 14)
  - Discord login with NextAuth
  - Protected routes via route group `(protected)`
  - Pages: Users (lists users), Marketplace → Listings (add items), Orders/Rewards/Quests/Events/Reports/Settings (stubs you can extend)
- API (Fastify)
  - `GET /users`: list users with balances
  - `GET /wallet/:discordId`: wallet + escrow
  - `POST /wallet/earn`: add coins (supports `Idempotency-Key`)
  - `POST /wallet/claim`: daily claim with 24h cooldown (`DAILY_CLAIM`)
  - `GET/POST /listings`: DB‑backed listings
  - `GET /healthz`: healthcheck
  - `GET /streams/tx`: sample SSE (keep‑alive)
- Bot (discord.js v14)
  - Auto‑registers guild slash commands: `/ping`, `/card`, `/claim`
  - Announces online in `MAIN_CHANNEL_ID`
  - Talks to the API (uses `API_BASE_URL` inside compose)
- Data
  - Postgres + Prisma schema for users, wallets, transactions, listings
  - Redis (future rate limits, queues)

## File Layout

- `apps/ui` — Next.js panel
- `apps/api` — Fastify API + Prisma
- `apps/bot` — Discord bot
- `docker-compose.yml` — runs db, cache, api, bot, ui
- `.env.example` — all environment variables you can set

## Environment Variables (most important)

- Discord
  - `DISCORD_TOKEN`, `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`, `GUILD_ID`, `MAIN_CHANNEL_ID`
- URLs
  - `PANEL_BASE_URL` (public panel URL)
  - `API_BASE_URL` (public API URL)
  - `NEXTAUTH_URL` (must equal public panel URL)
- Database / Cache
  - `DATABASE_URL` (compose defaults work out of the box)
  - `REDIS_URL` (compose defaults work out of the box)
- Auth
  - `NEXTAUTH_SECRET` (generate a long random string)
- Economy
  - `DAILY_CLAIM` (default 100)

Note: Inside Docker, services talk over the internal network. The UI gets both the public `NEXT_PUBLIC_API_BASE_URL` (from your `.env`) and an internal `API_BASE_URL=http://api:8080` for server‑side calls.

## Common Tasks

- Rebuild everything
  - `docker compose build --no-cache && docker compose up -d`
- View logs
  - `docker compose logs -f api`
  - `docker compose logs -f ui`
  - `docker compose logs -f bot`
- Test bot commands in your server
  - `/ping` → Pong + latency
  - `/card` → Shows your wallet
  - `/claim` → Daily coins (24h cooldown)
- Use the panel
  - Listings: create items (stored in Postgres)
  - Users: see users as they appear (created on first API interaction)

## Troubleshooting (read me first)

- “405 on /api/auth/providers”
  - Ensure the NextAuth route is wired (it is) and `NEXTAUTH_URL` matches your panel hostname.
- “Bot didn’t post”
  - Check the bot has permission in `MAIN_CHANNEL_ID` and the ID is correct. See logs.
- “Login fails / callback mismatch”
  - Discord OAuth Redirect must be exactly `https://YOUR_PANEL/api/auth/callback/discord` and match `NEXTAUTH_URL`.
- UI 404s on pages
  - We shipped stubs for all top‑nav pages; rebuild if you don’t see them.
- Can’t reach services publicly
  - If using Cloudflare, point DNS to your host and use “Full” SSL. Compose still serves HTTP on `3000` and `8080` internally.

## Roadmap (what’s next)

- Escrow and orders (list → buy → fulfil/refund) with fees & floors
- Admin transaction feed channel with actionable embeds
- Rewards catalog (ranks, cosmetics), quests/trivia
- Worker for expiries, retries, price windows, leaderboards
- Minecraft fulfilment (direct API + voucher mode)

## Safety & Secrets

- Never commit real secrets. Use `.env` for local, Docker secrets for prod.
- Keep your Discord Bot token private. Rotate if leaked.
- The containers run as non‑root where possible.

Happy building! If you want help wiring the next feature (escrow or admin feed), open an issue or ask for a PR plan.

