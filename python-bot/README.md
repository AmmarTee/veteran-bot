# Veteran Club Discord Bot

This repository contains a fully‑functional Discord bot that gamifies the
experience of being a **veteran** member on your server. The bot keeps
veterans active in a dedicated chat, rewards them with coins and XP for
participating, and lets them grow a virtual plant. When a veteran’s
plant dies (because it hasn’t been watered on time) their veteran role
is automatically removed.

## Features

- Rewards for chatting: The bot listens to messages in one or more configured channels and awards XP and coins to veteran members (with cooldown).
- Watering mechanic: Veterans spend coins to water their plants; water decreases over time. At zero the plant dies and the veteran role is removed.
- Coin transfers: Veterans can send coins to other veterans with a daily limit.
- Leaderboard: Top veterans ranked by plant age and XP.
- Slash commands for admins: Configure channels, tune values, seed panels, resync, give coins, revive.

## Deployment niceties

- Auto command sync on deploy: On startup the bot syncs slash commands to all joined guilds for immediate updates.
- Status announcements: Posts online/offline messages in the Garden channel during restarts/updates.

## How To Play

- Earn rewards by chatting in configured channels (cooldown applies).
- Keep your plant alive using the Garden panel’s "💧 Water My Plant" (costs coins).
- Daily check-in via "📅 Daily Check-In" for bonus coins/XP and streaks.
- Send coins to other veterans with "💸 Send Coins" (daily limit).
- View leaderboard with the panel or `/leaderboard`.

Tips:
- The Garden panel shows time left until dry and coins.
- Use `/mystats` for an ephemeral card with level, coins, XP, and time left.

## Admin Commands

- Setup: `/setup_veteran`, `/setup_garden`, `/setup_leaderboard`
- Reward channels: `/rewards_add`, `/rewards_remove`, `/rewards_set`, `/rewards_list`
- Tuning: `/set_economy`, `/set_degrade`, `/set_limits`, `/warnings`
- Maintenance: `/seed_garden`, `/seed_leaderboard`, `/resync_veterans`, `/give_coins`, `/revive`
- User: `/leaderboard`, `/mystats`

## Installation

1. Install dependencies: `python3 -m pip install -U discord.py`
2. Provide the bot token in a `.env` file (see `.env.example`).
3. Run: `python3 bot.py`

