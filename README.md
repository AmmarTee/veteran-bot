# Coin Economy & Marketplace Bot (Discord.js)

This project implements a coin-based economy with an ephemeral player card, public shop with escrow, a leaderboard, and an admin transaction feed. It is designed to run alongside your other bots, with minimal setup.

## Features

- Ephemeral player card: balance, escrow, streaks
- Coin hub message with navigation buttons
- Public shop listings with Buy flow (escrow)
- Admin transaction feed with event logs
- Leaderboard channel (coins top list; placeholder wiring)
- SQLite by default for easy deployment (swap to Postgres later)

## Requirements

- Node.js 18+
- A Discord application and bot token

## Quick Start

1. Copy `.env.example` to `.env` and set `DISCORD_TOKEN`.
2. Install dependencies: `npm install`
3. (Optional) Register slash commands to a dev guild: set `APPLICATION_ID` and `TEST_GUILD_ID`, then run `npm run register`.
4. Run the bot: `npm start`.

## Environment

Required:

- `DISCORD_TOKEN`: your bot token

Optional:

- `DATABASE_URL`: path to SQLite file (default `./data/coins.db`)
- `APPLICATION_ID`: your app ID (for registration script)
- `TEST_GUILD_ID`: a guild to register commands for dev

## Commands

- `/setupcoinsystem` (admin): creates channels and posts a pinned hub message, stores config.

## Flows

### Coin Hub

- Buttons: My Card, Shop, Claim Daily, Help
- My Card: ephemeral embed with wallet and escrow balances
- Shop: ephemeral summary of active listings
- Claim Daily: placeholder for streak/daily rewards

### Shop & Escrow

- Sell: button opens a modal to create a listing (SKU, quantity, unit price); posts to `#shop` channel
- Buy: button moves coins from buyer wallet to escrow and logs an admin event
- Fulfil/refund: to be implemented; placeholders provided in DB + admin feed

## Database

SQLite schema is created automatically on first run: tables for `users`, `config`, `listings`, `orders`, `order_lines`, and `transactions`.

## Roadmap

- Fulfilment commands and escrow release/refund
- Dynamic pricing rules (floor, fee scaling, scarcity)
- Admin controls: refund, cancel, force fulfil, freeze user
- Leaderboard auto-update task
- Minecraft integration hooks (voucher or API)

## Security

- Keep your token secret. Never commit `.env`.
- Rotate the token if it’s ever exposed.

