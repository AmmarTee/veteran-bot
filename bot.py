"""
Veteran Club Discord Bot — Single Garden Panel + Separate Leaderboard

- One "Garden" channel shows every veteran on a single panel:
  * Per-veteran row: plant icon (growth stage), water bar, level/XP, age, coins
  * Buttons on the panel: 💧 Water My Plant, 💸 Send Coins, 📅 Daily Check-In
  * Only the pressing veteran can water their own plant or send coins from their balance
- Separate "Leaderboard" channel has ONE pinned message with a sleek leaderboard
  * Only the leaderboard message itself has the 🔄 Refresh button (1/day per veteran)
- Daily low-water warning to reward channels at a configured Asia/Karachi local hour
- Coins/XP from chatting in configured reward channels, with anti-spam cooldown
- Plants degrade; at 0 they die → veteran role removed + row disappears on next refresh

Slash commands (admin unless noted):
  /configure            (admin) set IDs and tuning live
  /resync_veterans      (admin) scan role, rebuild panel
  /seed_garden          (admin) create/refresh the Garden panel
  /seed_leaderboard     (admin) create/refresh the Leaderboard panel
  /leaderboard                 post a one-off leaderboard in the current channel (no button)
  /mystats                     ephemeral personal stats + buttons

Requirements: discord.py >= 2.1
"""

from __future__ import annotations

import json
import os
from typing import Dict, Optional, List, Any, Iterable

from datetime import datetime, date, UTC, timedelta
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks


# ---------------- Persistence ----------------
DATA_FILE = os.path.join(os.path.dirname(__file__), "data.json")
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")


def load_json(path: str, default: Any) -> Any:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default


def save_json(path: str, data: Any) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
    os.replace(tmp, path)


def now_ts() -> float:
    return datetime.now(UTC).timestamp()


# ---------------- Model ----------------
class VeteranData:
    def __init__(self, user_id: int, data: Dict[str, Any], config: Dict[str, Any]):
        self.user_id = user_id
        self.config = config

        self.coins: int = data.get("coins", 0)
        self.xp: int = data.get("xp", 0)
        self.plant_start: float = data.get("plant_start", now_ts())
        self.water_level: float = data.get("water_level", config.get("plant_max_water", 100))
        self.last_message_time: float = data.get("last_message_time", 0.0)
        self.coins_sent_today: int = data.get("coins_sent_today", 0)
        self.last_coins_reset: str = data.get("last_coins_reset", date.today().isoformat())

        # Daily systems
        self.last_daily_claim: str = data.get("last_daily_claim", "")
        self.daily_streak: int = data.get("daily_streak", 0)
        self.last_lb_refresh: str = data.get("last_lb_refresh", "")  # per-user LB refresh cooldown

    def to_dict(self) -> Dict[str, Any]:
        return {
            "coins": self.coins,
            "xp": self.xp,
            "plant_start": self.plant_start,
            "water_level": self.water_level,
            "last_message_time": self.last_message_time,
            "coins_sent_today": self.coins_sent_today,
            "last_coins_reset": self.last_coins_reset,
            "last_daily_claim": self.last_daily_claim,
            "daily_streak": self.daily_streak,
            "last_lb_refresh": self.last_lb_refresh,
        }

    def add_xp_coins(self, xp_amount: int, coin_amount: int) -> None:
        self.xp += xp_amount
        self.coins += coin_amount

    @property
    def age_days(self) -> float:
        return (now_ts() - self.plant_start) / 86400

    @property
    def level(self) -> int:
        return int((self.xp / 10) ** 0.5) + 1

    def reset_daily_limit(self) -> None:
        today = date.today().isoformat()
        if self.last_coins_reset != today:
            self.coins_sent_today = 0
            self.last_coins_reset = today

    def can_send(self, amount: int) -> bool:
        self.reset_daily_limit()
        limit = self.config.get("max_coins_send_per_day", 100)
        return amount > 0 and self.coins >= amount and (self.coins_sent_today + amount) <= limit

    def record_send(self, amount: int) -> None:
        self.reset_daily_limit()
        self.coins_sent_today += amount
        self.coins -= amount

    def receive(self, amount: int) -> None:
        self.coins += amount

    def water_plant(self) -> bool:
        cost = self.config.get("water_cost", 10)
        maxw = self.config.get("plant_max_water", 100)
        if self.coins >= cost:
            self.coins -= cost
            self.water_level = maxw
            return True
        return False

    def degrade(self) -> None:
        self.water_level -= self.config.get("water_decrease_amount", 1)

    def is_alive(self) -> bool:
        return self.water_level > 0


# ---------------- Bot ----------------
class VeteranBot(commands.Bot):
    # Set this to your guild for instant slash sync
    TEST_GUILD_ID = 740784147798163508

    def __init__(self, **kwargs: Any) -> None:
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True
        intents.messages = True
        intents.message_content = True

        super().__init__(intents=intents, **kwargs)

        self.config: Dict[str, Any] = load_json(
            CONFIG_FILE,
            {
                # Role + channels
                "veteran_role_id": 0,
                "reward_channel_ids": [],

                # Single-panel Garden
                "garden_channel_id": 0,
                "garden_message_id": 0,

                # Leaderboard panel
                "leaderboard_channel_id": 0,
                "leaderboard_message_id": 0,

                # Plant & economy
                "water_cost": 10,
                "plant_max_water": 100,
                "water_decrease_interval_minutes": 60,
                "water_decrease_amount": 1,
                "xp_per_message": 5,
                "coins_per_message": 2,
                "message_cooldown_seconds": 60,
                "max_coins_send_per_day": 100,

                # Warnings (Asia/Karachi)
                "low_water_threshold": 20,
                "daily_warning_hour_local": 20,  # 8pm Karachi
                "warn_ping_veteran_role": 1,

                # Daily check-in rewards
                "daily_base_coins": 10,
                "daily_base_xp": 5,
                "daily_streak_bonus_coins": 2,
                "daily_streak_bonus_xp": 1,
                "daily_streak_cap": 7,
            },
        )

        self.veterans: Dict[int, VeteranData] = {}
        data = load_json(DATA_FILE, {})
        for uid_str, v in data.items():
            try:
                uid = int(uid_str)
                self.veterans[uid] = VeteranData(uid, v, self.config)
            except ValueError:
                continue

    # ------------- Utils / Renders -------------
    def save_all(self) -> None:
        save_json(DATA_FILE, {str(uid): v.to_dict() for uid, v in self.veterans.items()})

    def render_bar(self, current: float, maximum: int, width: int = 12) -> str:
        maximum = max(1, int(maximum))
        current = int(max(0, min(maximum, int(current))))
        filled = int(round((current / maximum) * width))
        return "█" * filled + "░" * (width - filled)

    def plant_emoji(self, v: VeteranData) -> str:
        if not v.is_alive():
            return "💀"
        if v.water_level <= self.config.get("low_water_threshold", 20):
            return "🥀"
        lvl = v.level
        if lvl < 3:
            return "🌱"
        if lvl < 6:
            return "🌿"
        if lvl < 10:
            return "🪴"
        return "🌳"

    def build_stats_embed(self, member: discord.Member | discord.User, v: VeteranData) -> discord.Embed:
        e = discord.Embed(title=f"{member.display_name}'s Plant", colour=discord.Colour.green())
        e.add_field(name="Level", value=str(v.level), inline=True)
        e.add_field(name="XP", value=str(v.xp), inline=True)
        e.add_field(name="Coins", value=str(v.coins), inline=True)
        e.add_field(name="Age (days)", value=f"{v.age_days:.1f}", inline=True)
        e.add_field(name="Water", value=f"{int(v.water_level)}/{self.config.get('plant_max_water', 100)}", inline=True)
        e.add_field(name="Water Bar", value=self.render_bar(v.water_level, self.config.get('plant_max_water', 100), 14), inline=False)
        e.set_footer(text="Use the buttons below in Garden or press /mystats anytime.")
        return e

    # ----- Garden panel (single message with all veterans) -----
    def build_garden_embeds(self, guild: discord.Guild) -> List[discord.Embed]:
        """Return up to 10 embeds containing all veterans in rows."""
        role_id = self.config.get("veteran_role_id", 0)
        role = guild.get_role(role_id) if role_id else None
        members: List[discord.Member] = list(role.members) if role else []

        # ensure a data record for each current veteran
        for m in members:
            if m.id not in self.veterans:
                self.veterans[m.id] = VeteranData(m.id, {}, self.config)

        # Only include those who still have the role
        rows: List[str] = []
        max_water = self.config.get("plant_max_water", 100)

        # Sort by age desc then XP desc
        sorted_pairs = sorted(
            ((m, self.veterans.get(m.id)) for m in members if self.veterans.get(m.id)),
            key=lambda t: (-t[1].age_days, -t[1].xp)
        )

        for idx, (m, v) in enumerate(sorted_pairs, start=1):
            bar = self.render_bar(v.water_level, max_water, 14)
            emoji = self.plant_emoji(v)
            rows.append(
                f"**{idx}. {emoji} {m.mention}** | {bar} {int(v.water_level)}/{max_water} "
                f"| L{v.level} XP:{v.xp} | {v.age_days:.1f}d | 💰{v.coins}"
            )

        if not rows:
            e = discord.Embed(title="🌿 Veteran Garden", description="No veterans detected yet.", colour=discord.Colour.green())
            return [e]

        # Chunk rows across multiple embeds if needed (Discord: max 4096 chars/description, max 10 embeds/msg)
        embeds: List[discord.Embed] = []
        chunk: List[str] = []
        total_chars = 0
        for line in rows:
            if total_chars + len(line) + 1 > 3500:  # keep buffer for safety
                embeds.append(discord.Embed(title="🌿 Veteran Garden", description="\n".join(chunk), colour=discord.Colour.green()))
                chunk = []
                total_chars = 0
            chunk.append(line)
            total_chars += len(line) + 1
        if chunk:
            embeds.append(discord.Embed(title="🌿 Veteran Garden", description="\n".join(chunk), colour=discord.Colour.green()))

        # Footer on last embed
        embeds[-1].set_footer(text="Use the buttons below: 💧 Water • 💸 Send • 📅 Daily")
        return embeds[:10]  # hard cap

    def build_garden_view(self) -> discord.ui.View:
        """Buttons available on the single Garden panel. No leaderboard button here."""
        view = discord.ui.View(timeout=None)
        bot = self

        # Water my plant
        async def water_cb(inter: discord.Interaction):
            role_id = bot.config.get("veteran_role_id", 0)
            if not role_id or not inter.guild:
                await inter.response.send_message("Watering unavailable.", ephemeral=True)
                return
            if not any(r.id == role_id for r in inter.user.roles):
                await inter.response.send_message("Only veterans can water a plant.", ephemeral=True)
                return

            v = bot.veterans.get(inter.user.id)
            if not v:
                v = VeteranData(inter.user.id, {}, bot.config)
                bot.veterans[inter.user.id] = v

            if v.water_plant():
                bot.save_all()
                # Update garden panel
                await bot.ensure_garden_panel(inter.guild)
                await inter.response.send_message("Watered! 🌱", ephemeral=True)
            else:
                await inter.response.send_message("Not enough coins to buy water.", ephemeral=True)

        btn_water = discord.ui.Button(label="💧 Water My Plant", style=discord.ButtonStyle.primary, custom_id="garden:water")
        btn_water.callback = water_cb
        view.add_item(btn_water)

        # Send coins (modal)
        async def send_open_modal(inter: discord.Interaction):
            role_id = bot.config.get("veteran_role_id", 0)
            if not role_id or not inter.guild:
                await inter.response.send_message("Sending unavailable.", ephemeral=True)
                return
            if not any(r.id == role_id for r in inter.user.roles):
                await inter.response.send_message("Only veterans can send coins.", ephemeral=True)
                return

            if inter.user.id not in bot.veterans:
                bot.veterans[inter.user.id] = VeteranData(inter.user.id, {}, bot.config)

            class SendCoinsModal(discord.ui.Modal, title="Send Coins"):
                recipient = discord.ui.TextInput(
                    label="Recipient ID or mention",
                    placeholder="e.g., 123456789012345678",
                    required=True,
                )
                amount = discord.ui.TextInput(
                    label="Amount",
                    placeholder="Number of coins",
                    required=True,
                )

                async def on_submit(self, mi: discord.Interaction) -> None:
                    sender = bot.veterans.get(inter.user.id)
                    raw = self.recipient.value.replace("<@", "").replace("<@!", "").replace(">", "")
                    try:
                        target_id = int(raw)
                        amt = int(self.amount.value)
                    except ValueError:
                        await mi.response.send_message("Invalid input. Provide numeric ID and amount.", ephemeral=True)
                        return
                    if amt <= 0 or target_id == inter.user.id:
                        await mi.response.send_message("Amount must be positive and recipient must be different.", ephemeral=True)
                        return
                    target = bot.veterans.get(target_id)
                    if not target:
                        await mi.response.send_message("Recipient is not a veteran.", ephemeral=True)
                        return
                    if not sender.can_send(amt):
                        await mi.response.send_message("Cannot send that many coins (daily limit/insufficient funds).", ephemeral=True)
                        return
                    sender.record_send(amt)
                    target.receive(amt)
                    bot.save_all()
                    await bot.ensure_garden_panel(inter.guild)
                    await mi.response.send_message(f"Sent {amt} coins to <@{target_id}>.", ephemeral=True)

            await inter.response.send_modal(SendCoinsModal())

        btn_send = discord.ui.Button(label="💸 Send Coins", style=discord.ButtonStyle.secondary, custom_id="garden:send")
        btn_send.callback = send_open_modal
        view.add_item(btn_send)

        # Daily check-in
        async def daily_cb(inter: discord.Interaction):
            role_id = bot.config.get("veteran_role_id", 0)
            if not role_id or not inter.guild:
                await inter.response.send_message("Daily unavailable.", ephemeral=True)
                return
            if not any(r.id == role_id for r in inter.user.roles):
                await inter.response.send_message("Only veterans can check in.", ephemeral=True)
                return

            v = bot.veterans.get(inter.user.id)
            if not v:
                v = VeteranData(inter.user.id, {}, bot.config)
                bot.veterans[inter.user.id] = v

            today = date.today().isoformat()
            if v.last_daily_claim == today:
                await inter.response.send_message("You’ve already claimed today.", ephemeral=True)
                return

            # Streak logic (UTC day boundary)
            yesterday = (date.today() - timedelta(days=1)).isoformat()
            if v.last_daily_claim == yesterday:
                v.daily_streak += 1
            else:
                v.daily_streak = 1

            base_c = bot.config.get("daily_base_coins", 10)
            base_x = bot.config.get("daily_base_xp", 5)
            cap = bot.config.get("daily_streak_cap", 7)
            bonus_c = bot.config.get("daily_streak_bonus_coins", 2) * min(v.daily_streak, cap)
            bonus_x = bot.config.get("daily_streak_bonus_xp", 1) * min(v.daily_streak, cap)

            v.coins += base_c + bonus_c
            v.xp += base_x + bonus_x
            v.last_daily_claim = today

            bot.save_all()
            await bot.ensure_garden_panel(inter.guild)
            await inter.response.send_message(
                f"Daily ✅  Streak **{v.daily_streak}**  +{base_c+bonus_c} coins, +{base_x+bonus_x} XP",
                ephemeral=True
            )

        btn_daily = discord.ui.Button(label="📅 Daily Check-In", style=discord.ButtonStyle.success, custom_id="garden:daily")
        btn_daily.callback = daily_cb
        view.add_item(btn_daily)

        return view

    async def ensure_garden_panel(self, guild: discord.Guild) -> None:
        ch_id = int(self.config.get("garden_channel_id") or 0)
        if not ch_id:
            return
        ch = guild.get_channel(ch_id)
        if not isinstance(ch, discord.TextChannel):
            return

        embeds = self.build_garden_embeds(guild)
        view = self.build_garden_view()
        msg_id = int(self.config.get("garden_message_id") or 0)

        if msg_id:
            try:
                msg = await ch.fetch_message(msg_id)
                await msg.edit(embeds=embeds, view=view)
                return
            except Exception:
                self.config["garden_message_id"] = 0
                save_json(CONFIG_FILE, self.config)

        msg = await ch.send(embeds=embeds, view=view)
        self.config["garden_message_id"] = msg.id
        save_json(CONFIG_FILE, self.config)
        try:
            await msg.pin()
        except discord.Forbidden:
            pass

    # ----- Leaderboard panel (separate channel; button only here) -----
    def build_leaderboard_embed(self, guild: Optional[discord.Guild] = None) -> discord.Embed:
        # prettier leaderboard with medals and compact stats
        embed = discord.Embed(title="🏆 Veteran Leaderboard", colour=discord.Colour.gold())
        if not self.veterans:
            embed.description = "No veterans yet."
            return embed

        # Rank by XP first, then age
        ranked = sorted(self.veterans.items(), key=lambda kv: (-kv[1].xp, -kv[1].age_days))
        lines: List[str] = []
        medals = ["🥇", "🥈", "🥉"]
        for i, (uid, v) in enumerate(ranked[:20], start=1):
            medal = medals[i-1] if i <= 3 else f"#{i}"
            mention = f"<@{uid}>"
            # relative XP bar (vs top)
            top_xp = max(ranked[0][1].xp, 1)
            bar = self.render_bar(v.xp, top_xp, 14)
            lines.append(f"**{medal} {mention}**  L{v.level}  XP:{v.xp}  {bar}  ⏳{v.age_days:.1f}d  💰{v.coins}")
        embed.description = "\n".join(lines)
        embed.set_footer(text="Press the button below to refresh (1/day per veteran).")
        return embed

    def build_leaderboard_view(self) -> discord.ui.View:
        view = discord.ui.View(timeout=None)
        bot = self

        async def refresh_cb(inter: discord.Interaction):
            role_id = bot.config.get("veteran_role_id", 0)
            if not role_id or not inter.guild:
                await inter.response.send_message("Leaderboard refresh not available.", ephemeral=True)
                return
            if not any(r.id == role_id for r in inter.user.roles):
                await inter.response.send_message("Only veterans can refresh the leaderboard.", ephemeral=True)
                return

            # per-user daily cooldown
            v = bot.veterans.get(inter.user.id)
            if not v:
                v = VeteranData(inter.user.id, {}, bot.config)
                bot.veterans[inter.user.id] = v

            today = date.today().isoformat()
            if v.last_lb_refresh == today:
                await inter.response.send_message("You’ve already refreshed today. Try again tomorrow.", ephemeral=True)
                return

            v.last_lb_refresh = today
            bot.save_all()

            try:
                await inter.response.edit_message(embed=bot.build_leaderboard_embed(inter.guild), view=bot.build_leaderboard_view())
            except discord.InteractionResponded:
                await inter.followup.edit_message(inter.message.id, embed=bot.build_leaderboard_embed(inter.guild), view=bot.build_leaderboard_view())

        btn = discord.ui.Button(label="🔄 Refresh Leaderboard (1/day)", style=discord.ButtonStyle.primary, custom_id="lb:refresh:global")
        btn.callback = refresh_cb
        view.add_item(btn)
        return view

    async def ensure_leaderboard_panel(self, guild: discord.Guild) -> None:
        ch_id = int(self.config.get("leaderboard_channel_id") or 0)
        if not ch_id:
            return
        ch = guild.get_channel(ch_id)
        if not isinstance(ch, discord.TextChannel):
            return

        embed = self.build_leaderboard_embed(guild)
        view = self.build_leaderboard_view()
        msg_id = int(self.config.get("leaderboard_message_id") or 0)

        if msg_id:
            try:
                msg = await ch.fetch_message(msg_id)
                await msg.edit(embed=embed, view=view)
                return
            except Exception:
                self.config["leaderboard_message_id"] = 0
                save_json(CONFIG_FILE, self.config)

        msg = await ch.send(embed=embed, view=view)
        self.config["leaderboard_message_id"] = msg.id
        save_json(CONFIG_FILE, self.config)
        try:
            await msg.pin()
        except discord.Forbidden:
            pass

    # ------------- Role/Scan/Resync -------------
    async def resync_guild_veterans(self, guild: discord.Guild) -> None:
        role_id = self.config.get("veteran_role_id", 0)
        if not role_id:
            return
        role = guild.get_role(role_id)
        if not role:
            return

        should_be = {m.id for m in role.members}

        # ensure data for members with role
        for m in role.members:
            if m.id not in self.veterans:
                self.veterans[m.id] = VeteranData(m.id, {}, self.config)

        # remove anyone who lost the role
        for uid in list(self.veterans.keys()):
            if uid not in should_be:
                self.veterans.pop(uid, None)

        self.save_all()
        await self.ensure_garden_panel(guild)
        await self.ensure_leaderboard_panel(guild)

    # ------------- Slash Commands & Setup -------------
    async def setup_hook(self) -> None:
        # /configure
        @self.tree.command(name="configure", description="Configure bot settings (admin only)")
        @discord.app_commands.describe(setting="Setting name", value="New value (IDs as integers; comma-list for reward_channel_ids)")
        async def configure(inter: discord.Interaction, setting: str, value: str):
            if not (inter.user.guild_permissions.manage_guild or inter.user.guild_permissions.administrator):
                await inter.response.send_message("You do not have permission.", ephemeral=True)
                return

            key = setting
            int_keys = {
                "veteran_role_id", "water_cost", "plant_max_water", "water_decrease_interval_minutes",
                "water_decrease_amount", "xp_per_message", "coins_per_message", "message_cooldown_seconds",
                "max_coins_send_per_day", "low_water_threshold", "daily_warning_hour_local",
                "daily_base_coins", "daily_base_xp", "daily_streak_bonus_coins", "daily_streak_bonus_xp",
                "daily_streak_cap", "garden_channel_id", "leaderboard_channel_id", "warn_ping_veteran_role",
            }
            if key in int_keys:
                try:
                    self.config[key] = int(value)
                except ValueError:
                    await inter.response.send_message(f"Expected integer for {key}.", ephemeral=True)
                    return
                # reset stored message IDs if channel changed
                if key == "garden_channel_id":
                    self.config["garden_message_id"] = 0
                if key == "leaderboard_channel_id":
                    self.config["leaderboard_message_id"] = 0
            elif key == "reward_channel_ids":
                ids: List[int] = []
                for part in value.replace("<", "").replace(">", "").split(","):
                    part = part.strip()
                    if part.startswith("#"):
                        part = part.lstrip("#")
                    try:
                        ids.append(int(part))
                    except ValueError:
                        continue
                self.config[key] = ids
            else:
                await inter.response.send_message(f"Unknown setting: {key}", ephemeral=True)
                return

            save_json(CONFIG_FILE, self.config)
            await inter.response.send_message(f"Updated `{key}` = `{value}`.", ephemeral=True)

        # /leaderboard (one-off embed in current channel; no button)
        @self.tree.command(name="leaderboard", description="Show the veteran leaderboard here")
        async def leaderboard(inter: discord.Interaction):
            if inter.guild and isinstance(inter.channel, discord.abc.GuildChannel):
                perms = inter.channel.permissions_for(inter.guild.me)
                if not perms.send_messages or not perms.embed_links:
                    await inter.response.send_message("I need Send Messages + Embed Links.", ephemeral=True)
                    return
            await inter.response.send_message(embed=self.build_leaderboard_embed(inter.guild))

        # /mystats (ephemeral card + action buttons)
        @self.tree.command(name="mystats", description="Show your plant stats (ephemeral)")
        async def mystats(inter: discord.Interaction):
            v = self.veterans.get(inter.user.id)
            if not v:
                v = VeteranData(inter.user.id, {}, self.config)
                self.veterans[inter.user.id] = v
            await inter.response.send_message(embed=self.build_stats_embed(inter.user, v), view=self.build_garden_view(), ephemeral=True)

        # /resync_veterans
        @self.tree.command(name="resync_veterans", description="Scan Veteran role and rebuild panels (admin)")
        async def resync_veterans(inter: discord.Interaction):
            if not (inter.user.guild_permissions.manage_guild or inter.user.guild_permissions.administrator):
                await inter.response.send_message("You do not have permission.", ephemeral=True)
                return
            await inter.response.defer(ephemeral=True)
            await self.resync_guild_veterans(inter.guild)
            await inter.followup.send("Resynced veterans and panels.", ephemeral=True)

        # /seed_garden
        @self.tree.command(name="seed_garden", description="Create or refresh the Garden panel (admin)")
        async def seed_garden(inter: discord.Interaction):
            if not (inter.user.guild_permissions.manage_guild or inter.user.guild_permissions.administrator):
                await inter.response.send_message("You do not have permission.", ephemeral=True)
                return
            await inter.response.defer(ephemeral=True)
            await self.ensure_garden_panel(inter.guild)
            await inter.followup.send("Garden panel ensured.", ephemeral=True)

        # /seed_leaderboard
        @self.tree.command(name="seed_leaderboard", description="Create or refresh the Leaderboard panel (admin)")
        async def seed_leaderboard(inter: discord.Interaction):
            if not (inter.user.guild_permissions.manage_guild or inter.user.guild_permissions.administrator):
                await inter.response.send_message("You do not have permission.", ephemeral=True)
                return
            await inter.response.defer(ephemeral=True)
            await self.ensure_leaderboard_panel(inter.guild)
            await inter.followup.send("Leaderboard panel ensured.", ephemeral=True)

        # Persistent views
        self.add_view(self.build_garden_view())
        self.add_view(self.build_leaderboard_view())

        # Instant sync to your guild
        gobj = discord.Object(id=self.TEST_GUILD_ID)
        self.tree.copy_global_to(guild=gobj)
        await self.tree.sync(guild=gobj)

        # Start background tasks
        if not self.degrade_task.is_running():
            self.degrade_task.start()
        if not self.veteran_scan_task.is_running():
            self.veteran_scan_task.start()
        if not self.daily_warning_task.is_running():
            self.daily_warning_task.start()
        if not self.garden_refresh_task.is_running():
            self.garden_refresh_task.start()

    async def on_ready(self) -> None:
        print(f"Logged in as {self.user} (ID: {self.user.id})")
        for g in self.guilds:
            await self.resync_guild_veterans(g)
            await self.ensure_garden_panel(g)
            await self.ensure_leaderboard_panel(g)

    async def on_guild_join(self, guild: discord.Guild) -> None:
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        await self.resync_guild_veterans(guild)
        await self.ensure_garden_panel(guild)
        await self.ensure_leaderboard_panel(guild)

    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        role_id = self.config.get("veteran_role_id", 0)
        if not role_id:
            return
        had = any(r.id == role_id for r in before.roles)
        has = any(r.id == role_id for r in after.roles)
        if not had and has:
            # new veteran
            if after.id not in self.veterans:
                self.veterans[after.id] = VeteranData(after.id, {}, self.config)
            self.save_all()
            await self.ensure_garden_panel(after.guild)
            await self.ensure_leaderboard_panel(after.guild)
        elif had and not has:
            # lost veteran role
            self.veterans.pop(after.id, None)
            self.save_all()
            await self.ensure_garden_panel(after.guild)
            await self.ensure_leaderboard_panel(after.guild)

    # ------------- Rewards (chat) -------------
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return
        if message.channel.id not in self.config.get("reward_channel_ids", []):
            return

        role_id = self.config.get("veteran_role_id", 0)
        if not role_id or not discord.utils.get(message.author.roles, id=role_id):
            return

        v = self.veterans.get(message.author.id)
        if not v:
            v = VeteranData(message.author.id, {}, self.config)
            self.veterans[message.author.id] = v

        t = now_ts()
        if t - v.last_message_time < self.config.get("message_cooldown_seconds", 60):
            return
        v.last_message_time = t
        v.add_xp_coins(self.config.get("xp_per_message", 5), self.config.get("coins_per_message", 2))
        self.save_all()
        # Garden auto-refresh task runs periodically; avoid editing on every message

    # ------------- Background Tasks -------------
    @tasks.loop(minutes=1.0)
    async def degrade_task(self) -> None:
        t = now_ts()
        interval = self.config.get("water_decrease_interval_minutes", 60) * 60

        if not hasattr(self.degrade_task, "last"):
            setattr(self.degrade_task, "last", t)
            return
        last = getattr(self.degrade_task, "last")
        if t - last < interval:
            return
        setattr(self.degrade_task, "last", t)

        changed = False
        for uid, v in list(self.veterans.items()):
            v.degrade()
            if v.is_alive():
                continue

            # Plant died: remove role
            for g in self.guilds:
                member = g.get_member(uid)
                if member:
                    role_id = self.config.get("veteran_role_id", 0)
                    if role_id:
                        role = g.get_role(role_id)
                        if role:
                            try:
                                await member.remove_roles(role, reason="Plant died")
                            except discord.Forbidden:
                                pass
            # Remove from state
            del self.veterans[uid]
            changed = True

        if changed:
            self.save_all()
            # Refresh panels for all guilds
            for g in self.guilds:
                await self.ensure_garden_panel(g)
                await self.ensure_leaderboard_panel(g)

    @tasks.loop(minutes=5.0)
    async def veteran_scan_task(self) -> None:
        for g in self.guilds:
            await self.resync_guild_veterans(g)

    @tasks.loop(minutes=5.0)
    async def garden_refresh_task(self) -> None:
        """Periodic gentle refresh of the Garden panel."""
        for g in self.guilds:
            await self.ensure_garden_panel(g)

    @tasks.loop(minutes=5.0)
    async def daily_warning_task(self) -> None:
        """
        If local (Asia/Karachi) time is within the first 5 minutes of the configured hour,
        post a low-water reminder in each reward channel (once per day per guild).
        """
        if not self.config.get("reward_channel_ids"):
            return

        tz = ZoneInfo("Asia/Karachi")
        now_local = datetime.now(tz)
        target_hour = int(self.config.get("daily_warning_hour_local", 20))
        if not (now_local.hour == target_hour and now_local.minute < 5):
            return

        key = "daily_warning_last"
        if key not in self.config or not isinstance(self.config[key], dict):
            self.config[key] = {}
        today_iso = now_local.date().isoformat()

        for guild in self.guilds:
            last = self.config[key].get(str(guild.id), "")
            if last == today_iso:
                continue  # already warned today

            role_id = self.config.get("veteran_role_id", 0)
            if not role_id:
                continue
            role = guild.get_role(role_id)
            if not role:
                continue

            low = []
            for m in role.members:
                v = self.veterans.get(m.id)
                if v and v.water_level <= self.config.get("low_water_threshold", 20):
                    low.append(m)

            ping = f"<@&{role_id}> " if int(self.config.get("warn_ping_veteran_role", 1)) == 1 else ""
            if low:
                names = ", ".join(m.mention for m in low[:20])
                content = (
                    f"{ping}🌵 **Daily Water Warning** — Some plants are drying out!\n"
                    f"{names}\n"
                    f"Use **💧 Water My Plant** on the Garden panel."
                )
            else:
                content = f"{ping}🌿 **Daily Garden Reminder** — Keep chatting and watering to grow your plants!"

            for ch_id in self.config.get("reward_channel_ids", []):
                ch = guild.get_channel(int(ch_id))
                if isinstance(ch, discord.TextChannel):
                    perms = ch.permissions_for(guild.me)
                    if perms.send_messages:
                        try:
                            await ch.send(content)
                        except Exception:
                            pass

            self.config[key][str(guild.id)] = today_iso
            save_json(CONFIG_FILE, self.config)


# ------------- Entrypoint -------------
def main() -> None:
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        env = os.path.join(os.path.dirname(__file__), ".env")
        if os.path.exists(env):
            with open(env, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    k, _, v = line.partition("=")
                    if k == "DISCORD_TOKEN":
                        token = v.strip()
                        break
    if not token:
        raise RuntimeError("Bot token not found. Set DISCORD_TOKEN or put it in .env")

    bot = VeteranBot(command_prefix="!")
    bot.run(token)


if __name__ == "__main__":
    main()
