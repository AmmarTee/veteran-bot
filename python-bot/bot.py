"""
Veteran Club Bot — Single Garden + Top-5 Leaderboard

- Garden channel: one minimal panel (everyone): plant emoji + TIME LEFT until dry.
  * Buttons: 💧 Water My Plant (owner only), 💸 Send Coins (picker + amount buttons), 📅 Daily Check-In
  * NO XP shown here.
- Leaderboard channel: Top-5 only; XP bar, level, age, coins. Refresh button on the panel (1/day per veteran).
- Rewards: chat in configured reward channels grants XP/coins (cooldown) and counts toward daily survival.
- Survival: must send >= daily_min_messages messages per local day (Asia/Karachi) in reward channels; else plant dies.
- Admin commands: typed (no raw variable names). See section below.

Commands:
  Setup:
    /setup_veteran role:<Role>
    /setup_garden channel:<TextChannel>
    /setup_leaderboard channel:<TextChannel>
    /setup_rewards channels:<TextChannel...>
  Tuning:
    /set_economy water_cost:<int> plant_max_water:<int> xp_per_message:<int> coins_per_message:<int> cooldown:<int>
    /set_degrade interval_minutes:<int> decrease_amount:<int>
    /set_limits max_send_per_day:<int> daily_min_messages:<int>
    /warnings enabled:<bool> hour:<int>
  Maintenance:
    /seed_garden
    /seed_leaderboard
    /resync_veterans
    /give_coins member:<Member> amount:<int>
    /revive member:<Member>
  User:
    /leaderboard   (one-off post, no button)
    /mystats       (ephemeral personal card)

Author: You
"""

from __future__ import annotations

import json
import os
from typing import Dict, Optional, List, Any

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
        self.last_lb_refresh: str = data.get("last_lb_refresh", "")

        # Daily survival (local)
        self.messages_today: int = data.get("messages_today", 0)
        self.last_message_day_local: str = data.get("last_message_day_local", "")

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
            "messages_today": self.messages_today,
            "last_message_day_local": self.last_message_day_local,
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
    # set to your guild for instant slash sync
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
                "garden_channel_id": 0,
                "garden_message_id": 0,
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

                # Daily check-in rewards
                "daily_base_coins": 10,
                "daily_base_xp": 5,
                "daily_streak_bonus_coins": 2,
                "daily_streak_bonus_xp": 1,
                "daily_streak_cap": 7,

                # Warnings & survival
                "low_water_threshold": 20,
                "daily_warning_hour_local": 20,
                "warn_ping_veteran_role": 1,
                "daily_min_messages": 10,
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

        # Status announcement flags
        self._startup_announced: bool = False
        self._closing_announced: bool = False

    # ---------------- Utils / Render ----------------
    def save_all(self) -> None:
        save_json(DATA_FILE, {str(uid): v.to_dict() for uid, v in self.veterans.items()})

    def render_bar(self, current: float, maximum: int, width: int = 18) -> str:
        maximum = max(1, int(maximum))
        cur = max(0, min(maximum, int(current)))
        filled = int(round(cur / maximum * width))
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

    def minutes_left(self, v: VeteranData) -> int:
        """Estimated minutes until water hits zero, based on current config."""
        if not v.is_alive():
            return 0
        dec = max(1, int(self.config.get("water_decrease_amount", 1)))
        interval = max(1, int(self.config.get("water_decrease_interval_minutes", 60)))
        return int((v.water_level / dec) * interval)

    def fmt_duration(self, minutes: int) -> str:
        if minutes <= 0:
            return "dead"
        if minutes < 60:
            return f"{minutes}m"
        h = minutes // 60
        m = minutes % 60
        return f"{h}h {m}m" if m else f"{h}h"

    # ---------------- Garden (minimal) ----------------
    def build_garden_embeds(self, guild: discord.Guild) -> List[discord.Embed]:
        """Minimal, clean two-line rows: index + name, then fixed-width time left and coins."""
        role_id = self.config.get("veteran_role_id", 0)
        role = guild.get_role(role_id) if role_id else None
        members: List[discord.Member] = list(role.members) if role else []

        for m in members:
            if m.id not in self.veterans:
                self.veterans[m.id] = VeteranData(m.id, {}, self.config)

        rows: List[str] = []
        # Order by time left asc (urgency) then XP desc for engagement
        pairs = []
        for m in members:
            v = self.veterans.get(m.id)
            if not v:
                continue
            pairs.append((m, v, self.minutes_left(v)))
        pairs.sort(key=lambda t: (t[2], -t[1].xp))

        for idx, (m, v, mins) in enumerate(pairs, start=1):
            emoji = self.plant_emoji(v)
            # line 1: index + name + icon
            rows.append(f"**{idx:>2}. {emoji} {m.mention}**")
            # line 2: fixed-width details (no XP)
            tl = self.fmt_duration(mins)
            rows.append(f"`TIME LEFT {tl:>8} | 💰 {v.coins:>4}`")

        if not rows:
            e = discord.Embed(title="🌿 Veteran Garden", description="No veterans detected yet.", colour=discord.Colour.green())
            return [e]

        embeds: List[discord.Embed] = []
        chunk: List[str] = []
        total = 0
        for line in rows:
            if total + len(line) + 1 > 3500:
                embeds.append(discord.Embed(title="🌿 Veteran Garden", description="\n".join(chunk), colour=discord.Colour.green()))
                chunk, total = [], 0
            chunk.append(line)
            total += len(line) + 1
        if chunk:
            embeds.append(discord.Embed(title="🌿 Veteran Garden", description="\n".join(chunk), colour=discord.Colour.green()))
        embeds[-1].set_footer(text="Buttons below: 💧 Water • 💸 Send • 📅 Daily")
        return embeds[:10]

    def build_garden_view(self) -> discord.ui.View:
        """Buttons for Garden; no leaderboard button here."""
        view = discord.ui.View(timeout=None)
        bot = self

        # ---- Water ----
        async def water_cb(inter: discord.Interaction):
            role_id = bot.config.get("veteran_role_id", 0)
            if not role_id or not inter.guild:
                await inter.response.send_message("Watering unavailable.", ephemeral=True)
                return
            if not any(r.id == role_id for r in inter.user.roles):
                await inter.response.send_message("Only veterans can water.", ephemeral=True)
                return
            v = bot.veterans.get(inter.user.id)
            if not v:
                v = VeteranData(inter.user.id, {}, bot.config)
                bot.veterans[inter.user.id] = v
            if v.water_plant():
                bot.save_all()
                await bot.ensure_garden_panel(inter.guild)
                await inter.response.send_message("Watered! 💧", ephemeral=True)
            else:
                cost = bot.config.get("water_cost", 10)
                await inter.response.send_message(f"Not enough coins (cost {cost}).", ephemeral=True)

        btn_water = discord.ui.Button(label="💧 Water My Plant", style=discord.ButtonStyle.primary, custom_id="garden:water")
        btn_water.callback = water_cb
        view.add_item(btn_water)

        # ---- Send Coins (picker + amount buttons) ----
        class RecipientSelect(discord.ui.Select):
            def __init__(self, options: List[discord.SelectOption]):
                super().__init__(placeholder="Choose a veteran…", min_values=1, max_values=1, options=options, custom_id="send:select")

            async def callback(self, inter: discord.Interaction):
                self.view.selected_user_id = int(self.values[0])
                await inter.response.send_message("Recipient selected.", ephemeral=True)

        class CustomAmountModal(discord.ui.Modal, title="Custom Amount"):
            amount = discord.ui.TextInput(label="Amount", placeholder="Enter a positive integer", required=True)
            def __init__(self, outer_view: "SendCoinsView"):
                super().__init__()
                self.outer_view = outer_view

            async def on_submit(self, inter: discord.Interaction):
                try:
                    amt = int(str(self.amount.value).strip())
                except ValueError:
                    await inter.response.send_message("Amount must be an integer.", ephemeral=True)
                    return
                await self.outer_view.perform_transfer(inter, amt)

        class SendCoinsView(discord.ui.View):
            def __init__(self, bot_ref: "VeteranBot", sender_id: int, guild: discord.Guild):
                super().__init__(timeout=120)
                self.bot_ref = bot_ref
                self.sender_id = sender_id
                self.selected_user_id: Optional[int] = None

                # Build dropdown of veterans (excludes sender)
                role_id = bot_ref.config.get("veteran_role_id", 0)
                role = guild.get_role(role_id) if role_id else None
                vets = [m for m in (role.members if role else []) if m.id != sender_id][:25]
                opts = [discord.SelectOption(label=m.display_name, value=str(m.id)) for m in vets]
                if not opts:
                    opts = [discord.SelectOption(label="No other veterans found", value=str(sender_id))]
                self.add_item(RecipientSelect(opts))

                # Common amount buttons
                for amt in (5, 10, 25, 50, 100):
                    self.add_item(self.make_amount_button(amt))

                # Custom
                custom = discord.ui.Button(label="Custom…", style=discord.ButtonStyle.secondary, custom_id="send:custom")
                async def custom_cb(inter: discord.Interaction):
                    await inter.response.send_modal(CustomAmountModal(self))
                custom.callback = custom_cb
                self.add_item(custom)

            def make_amount_button(self, amt: int) -> discord.ui.Button:
                btn = discord.ui.Button(label=f"{amt}", style=discord.ButtonStyle.success, custom_id=f"send:{amt}")
                async def cb(inter: discord.Interaction):
                    await self.perform_transfer(inter, amt)
                btn.callback = cb
                return btn

            async def perform_transfer(self, inter: discord.Interaction, amount: int):
                if amount <= 0:
                    await inter.response.send_message("Amount must be positive.", ephemeral=True)
                    return
                if self.selected_user_id is None:
                    await inter.response.send_message("Pick a recipient first.", ephemeral=True)
                    return
                if self.selected_user_id == self.sender_id:
                    await inter.response.send_message("You can't send coins to yourself.", ephemeral=True)
                    return

                sender = self.bot_ref.veterans.get(self.sender_id)
                receiver = self.bot_ref.veterans.get(self.selected_user_id)
                if not sender or not receiver:
                    await inter.response.send_message("Both sender and recipient must be veterans.", ephemeral=True)
                    return
                if not sender.can_send(amount):
                    lim = self.bot_ref.config.get("max_coins_send_per_day", 100)
                    await inter.response.send_message(f"Insufficient funds or daily limit reached (limit {lim}).", ephemeral=True)
                    return
                sender.record_send(amount)
                receiver.receive(amount)
                self.bot_ref.save_all()
                await self.bot_ref.ensure_garden_panel(inter.guild)
                await inter.response.send_message(f"Sent **{amount}** coins to <@{self.selected_user_id}>.", ephemeral=True)

        async def send_open(inter: discord.Interaction):
            role_id = bot.config.get("veteran_role_id", 0)
            if not role_id or not inter.guild:
                await inter.response.send_message("Sending unavailable.", ephemeral=True)
                return
            if not any(r.id == role_id for r in inter.user.roles):
                await inter.response.send_message("Only veterans can send coins.", ephemeral=True)
                return
            if inter.user.id not in bot.veterans:
                bot.veterans[inter.user.id] = VeteranData(inter.user.id, {}, bot.config)
            await inter.response.send_message("Choose recipient and amount:", view=SendCoinsView(bot, inter.user.id, inter.guild), ephemeral=True)

        btn_send = discord.ui.Button(label="💸 Send Coins", style=discord.ButtonStyle.secondary, custom_id="garden:send")
        btn_send.callback = send_open
        view.add_item(btn_send)

        # ---- Daily check-in ----
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
            yesterday = (date.today() - timedelta(days=1)).isoformat()
            v.daily_streak = v.daily_streak + 1 if v.last_daily_claim == yesterday else 1
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

    # ---------------- Leaderboard (Top-5) ----------------
    def build_leaderboard_embed(self, guild: Optional[discord.Guild] = None) -> discord.Embed:
        embed = discord.Embed(title="🏆 Veteran Leaderboard", colour=discord.Colour.gold())
        if not self.veterans:
            embed.description = "No veterans yet."
            return embed

        ranked = sorted(self.veterans.items(), key=lambda kv: (-kv[1].xp, -kv[1].age_days))
        top = ranked[:5]
        top_xp = max(top[0][1].xp, 1)
        medals = ["🥇", "🥈", "🥉"]

        lines: List[str] = []
        for i, (uid, v) in enumerate(top, start=1):
            medal = medals[i-1] if i <= 3 else f"#{i}"
            mention = f"<@{uid}>"
            xp_bar = self.render_bar(v.xp, top_xp, 20)
            lines.append(f"**{medal} {mention}**  L{v.level}")
            lines.append(f"`XP [{xp_bar}] {v.xp:>4} | AGE {v.age_days:>4.1f}d | 💰 {v.coins:>4}`")

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
                await inter.response.send_message("Only veterans can refresh.", ephemeral=True)
                return
            v = bot.veterans.get(inter.user.id)
            if not v:
                v = VeteranData(inter.user.id, {}, bot.config)
                bot.veterans[inter.user.id] = v
            today = date.today().isoformat()
            if v.last_lb_refresh == today:
                await inter.response.send_message("You’ve already refreshed today.", ephemeral=True)
                return
            v.last_lb_refresh = today
            bot.save_all()
            try:
                await inter.response.edit_message(embed=bot.build_leaderboard_embed(inter.guild), view=bot.build_leaderboard_view())
            except discord.InteractionResponded:
                await inter.followup.edit_message(inter.message.id, embed=bot.build_leaderboard_embed(inter.guild), view=bot.build_leaderboard_view())

        btn = discord.ui.Button(label="🔄 Refresh Leaderboard (1/day)", style=discord.ButtonStyle.primary, custom_id="lb:refresh")
        btn.callback = refresh_cb
        view.add_item(btn)
        return view

    # ---------------- Status Announcements ----------------
    async def _get_status_channel(self, guild: discord.Guild) -> Optional[discord.TextChannel]:
        """Prefer the Garden channel for status messages."""
        ch_id = int(self.config.get("garden_channel_id") or 0)
        ch = guild.get_channel(ch_id) if ch_id else None
        return ch if isinstance(ch, discord.TextChannel) else None

    async def announce_status(self, guild: discord.Guild, online: bool) -> None:
        ch = await self._get_status_channel(guild)
        if not ch:
            return
        perms = ch.permissions_for(guild.me)
        if not perms.send_messages:
            return
        try:
            if online:
                await ch.send("🟢 Duck bot is now online after an update.")
            else:
                await ch.send("🔴 Duck bot is going offline for an update…")
        except Exception:
            pass

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

    # ---------------- Resync ----------------
    async def resync_guild_veterans(self, guild: discord.Guild) -> None:
        role_id = self.config.get("veteran_role_id", 0)
        if not role_id:
            return
        role = guild.get_role(role_id)
        if not role:
            return
        should = {m.id for m in role.members}
        for m in role.members:
            if m.id not in self.veterans:
                self.veterans[m.id] = VeteranData(m.id, {}, self.config)
        for uid in list(self.veterans.keys()):
            if uid not in should:
                self.veterans.pop(uid, None)
        self.save_all()
        await self.ensure_garden_panel(guild)
        await self.ensure_leaderboard_panel(guild)

    # ---------------- Slash Commands & Setup ----------------
    async def setup_hook(self) -> None:
        # ---- Setup (typed) ----
        @self.tree.command(name="setup_veteran", description="Set the Veteran role (admin)")
        async def setup_veteran(inter: discord.Interaction, role: discord.Role):
            if not (inter.user.guild_permissions.manage_guild or inter.user.guild_permissions.administrator):
                await inter.response.send_message("No permission.", ephemeral=True)
                return
            self.config["veteran_role_id"] = role.id
            save_json(CONFIG_FILE, self.config)
            await inter.response.send_message(f"Veteran role set to {role.mention}.", ephemeral=True)

        @self.tree.command(name="setup_garden", description="Set the Garden channel (admin)")
        async def setup_garden(inter: discord.Interaction, channel: discord.TextChannel):
            if not (inter.user.guild_permissions.manage_guild or inter.user.guild_permissions.administrator):
                await inter.response.send_message("No permission.", ephemeral=True)
                return
            self.config["garden_channel_id"] = channel.id
            self.config["garden_message_id"] = 0
            save_json(CONFIG_FILE, self.config)
            await inter.response.send_message(f"Garden channel set to {channel.mention}.", ephemeral=True)

        @self.tree.command(name="setup_leaderboard", description="Set the Leaderboard channel (admin)")
        async def setup_leaderboard(inter: discord.Interaction, channel: discord.TextChannel):
            if not (inter.user.guild_permissions.manage_guild or inter.user.guild_permissions.administrator):
                await inter.response.send_message("No permission.", ephemeral=True)
                return
            self.config["leaderboard_channel_id"] = channel.id
            self.config["leaderboard_message_id"] = 0
            save_json(CONFIG_FILE, self.config)
            await inter.response.send_message(f"Leaderboard channel set to {channel.mention}.", ephemeral=True)

        @self.tree.command(name="rewards_add", description="Add one reward channel (admin)")
        async def rewards_add(inter: discord.Interaction, channel: discord.TextChannel):
            if not (inter.user.guild_permissions.manage_guild or inter.user.guild_permissions.administrator):
                await inter.response.send_message("No permission.", ephemeral=True)
                return
            ids = set(int(x) for x in self.config.get("reward_channel_ids", []))
            ids.add(channel.id)
            self.config["reward_channel_ids"] = list(ids)
            save_json(CONFIG_FILE, self.config)
            await inter.response.send_message(f"Added reward channel: {channel.mention}", ephemeral=True)

        @self.tree.command(name="rewards_remove", description="Remove one reward channel (admin)")
        async def rewards_remove(inter: discord.Interaction, channel: discord.TextChannel):
            if not (inter.user.guild_permissions.manage_guild or inter.user.guild_permissions.administrator):
                await inter.response.send_message("No permission.", ephemeral=True)
                return
            ids = [int(x) for x in self.config.get("reward_channel_ids", [])]
            if channel.id in ids:
                ids.remove(channel.id)
                self.config["reward_channel_ids"] = ids
                save_json(CONFIG_FILE, self.config)
                await inter.response.send_message(f"Removed reward channel: {channel.mention}", ephemeral=True)
            else:
                await inter.response.send_message(f"{channel.mention} was not configured.", ephemeral=True)

        @self.tree.command(name="rewards_set", description="Set reward channels using a CSV of mentions or IDs (admin)")
        @discord.app_commands.describe(channels="Example: #chat-1, #chat-2 or 123,456")
        async def rewards_set(inter: discord.Interaction, channels: str):
            if not (inter.user.guild_permissions.manage_guild or inter.user.guild_permissions.administrator):
                await inter.response.send_message("No permission.", ephemeral=True)
                return
            ids: list[int] = []
            for part in channels.replace("<#", "").replace(">", "").split(","):
                part = part.strip().lstrip("#")
                if not part:
                    continue
                try:
                    ids.append(int(part))
                except ValueError:
                    continue
            self.config["reward_channel_ids"] = list(dict.fromkeys(ids))  # dedupe, keep order
            save_json(CONFIG_FILE, self.config)
            pretty = ", ".join(f"<#{i}>" for i in self.config["reward_channel_ids"]) or "(none)"
            await inter.response.send_message(f"Reward channels set: {pretty}", ephemeral=True)

        @self.tree.command(name="rewards_list", description="Show current reward channels (admin)")
        async def rewards_list(inter: discord.Interaction):
            ids = [int(x) for x in self.config.get("reward_channel_ids", [])]
            if not ids:
                await inter.response.send_message("No reward channels configured.", ephemeral=True)
                return
            pretty = "\n".join(f"• <#{i}>" for i in ids)
            await inter.response.send_message(f"Current reward channels:\n{pretty}", ephemeral=True)

        # ---- Tuning (typed numbers) ----
        @self.tree.command(name="set_economy", description="Set economy numbers (admin)")
        async def set_economy(
            inter: discord.Interaction,
            water_cost: int,
            plant_max_water: int,
            xp_per_message: int,
            coins_per_message: int,
            cooldown: int
        ):
            if not (inter.user.guild_permissions.manage_guild or inter.user.guild_permissions.administrator):
                await inter.response.send_message("No permission.", ephemeral=True)
                return
            self.config.update({
                "water_cost": water_cost,
                "plant_max_water": plant_max_water,
                "xp_per_message": xp_per_message,
                "coins_per_message": coins_per_message,
                "message_cooldown_seconds": cooldown,
            })
            save_json(CONFIG_FILE, self.config)
            await inter.response.send_message("Economy settings updated.", ephemeral=True)

        @self.tree.command(name="set_degrade", description="Set water degradation (admin)")
        async def set_degrade(inter: discord.Interaction, interval_minutes: int, decrease_amount: int):
            if not (inter.user.guild_permissions.manage_guild or inter.user.guild_permissions.administrator):
                await inter.response.send_message("No permission.", ephemeral=True)
                return
            self.config["water_decrease_interval_minutes"] = interval_minutes
            self.config["water_decrease_amount"] = decrease_amount
            save_json(CONFIG_FILE, self.config)
            await inter.response.send_message("Degrade settings updated.", ephemeral=True)

        @self.tree.command(name="set_limits", description="Set limits (admin)")
        async def set_limits(inter: discord.Interaction, max_send_per_day: int, daily_min_messages: int):
            if not (inter.user.guild_permissions.manage_guild or inter.user.guild_permissions.administrator):
                await inter.response.send_message("No permission.", ephemeral=True)
                return
            self.config["max_coins_send_per_day"] = max_send_per_day
            self.config["daily_min_messages"] = daily_min_messages
            save_json(CONFIG_FILE, self.config)
            await inter.response.send_message("Limits updated.", ephemeral=True)

        @self.tree.command(name="warnings", description="Configure daily low-water warnings (admin)")
        async def warnings(inter: discord.Interaction, enabled: bool, hour: int):
            if not (inter.user.guild_permissions.manage_guild or inter.user.guild_permissions.administrator):
                await inter.response.send_message("No permission.", ephemeral=True)
                return
            self.config["warn_ping_veteran_role"] = 1 if enabled else 0
            self.config["daily_warning_hour_local"] = hour
            save_json(CONFIG_FILE, self.config)
            await inter.response.send_message("Warning settings updated.", ephemeral=True)

        # ---- Maintenance ----
        @self.tree.command(name="seed_garden", description="Create/refresh the Garden panel (admin)")
        async def seed_garden(inter: discord.Interaction):
            if not (inter.user.guild_permissions.manage_guild or inter.user.guild_permissions.administrator):
                await inter.response.send_message("No permission.", ephemeral=True)
                return
            await inter.response.defer(ephemeral=True)
            await self.ensure_garden_panel(inter.guild)
            await inter.followup.send("Garden panel ensured.", ephemeral=True)

        @self.tree.command(name="seed_leaderboard", description="Create/refresh the Leaderboard panel (admin)")
        async def seed_leaderboard(inter: discord.Interaction):
            if not (inter.user.guild_permissions.manage_guild or inter.user.guild_permissions.administrator):
                await inter.response.send_message("No permission.", ephemeral=True)
                return
            await inter.response.defer(ephemeral=True)
            await self.ensure_leaderboard_panel(inter.guild)
            await inter.followup.send("Leaderboard panel ensured.", ephemeral=True)

        @self.tree.command(name="resync_veterans", description="Scan Veteran role and rebuild panels (admin)")
        async def resync_veterans(inter: discord.Interaction):
            if not (inter.user.guild_permissions.manage_guild or inter.user.guild_permissions.administrator):
                await inter.response.send_message("No permission.", ephemeral=True)
                return
            await inter.response.defer(ephemeral=True)
            await self.resync_guild_veterans(inter.guild)
            await inter.followup.send("Resynced veterans & panels.", ephemeral=True)

        @self.tree.command(name="give_coins", description="Give coins to a member (admin)")
        async def give_coins(inter: discord.Interaction, member: discord.Member, amount: int):
            if not (inter.user.guild_permissions.manage_guild or inter.user.guild_permissions.administrator):
                await inter.response.send_message("No permission.", ephemeral=True)
                return
            if amount <= 0:
                await inter.response.send_message("Amount must be positive.", ephemeral=True)
                return
            v = self.veterans.get(member.id) or VeteranData(member.id, {}, self.config)
            v.coins += amount
            self.veterans[member.id] = v
            self.save_all()
            await self.ensure_garden_panel(inter.guild)
            await inter.response.send_message(f"Gave {amount} coins to {member.mention}.", ephemeral=True)

        @self.tree.command(name="revive", description="Revive a member's plant (admin)")
        async def revive(inter: discord.Interaction, member: discord.Member):
            if not (inter.user.guild_permissions.manage_guild or inter.user.guild_permissions.administrator):
                await inter.response.send_message("No permission.", ephemeral=True)
                return
            v = self.veterans.get(member.id) or VeteranData(member.id, {}, self.config)
            v.water_level = self.config.get("plant_max_water", 100)
            v.plant_start = now_ts()
            self.veterans[member.id] = v
            self.save_all()
            await self.ensure_garden_panel(inter.guild)
            await inter.response.send_message(f"Revived {member.mention}'s plant.", ephemeral=True)

        # ---- User ----
        @self.tree.command(name="leaderboard", description="Post the Top-5 leaderboard here")
        async def leaderboard(inter: discord.Interaction):
            if inter.guild and isinstance(inter.channel, discord.abc.GuildChannel):
                perms = inter.channel.permissions_for(inter.guild.me)
                if not perms.send_messages or not perms.embed_links:
                    await inter.response.send_message("I need Send Messages + Embed Links.", ephemeral=True)
                    return
            await inter.response.send_message(embed=self.build_leaderboard_embed(inter.guild))

        @self.tree.command(name="mystats", description="Show your plant stats (ephemeral)")
        async def mystats(inter: discord.Interaction):
            v = self.veterans.get(inter.user.id) or VeteranData(inter.user.id, {}, self.config)
            self.veterans[inter.user.id] = v
            mins = self.minutes_left(v)
            e = discord.Embed(title=f"{inter.user.display_name}'s Plant", colour=discord.Colour.green())
            e.add_field(name="Level", value=str(v.level), inline=True)
            e.add_field(name="Coins", value=str(v.coins), inline=True)
            e.add_field(name="Time Left", value=self.fmt_duration(mins), inline=True)
            e.add_field(name="XP (Leaderboard only)", value=str(v.xp), inline=True)
            e.set_footer(text="Use Garden buttons for actions.")
            await inter.response.send_message(embed=e, view=self.build_garden_view(), ephemeral=True)

        # Persistent views
        self.add_view(self.build_garden_view())
        self.add_view(self.build_leaderboard_view())

        # Instant sync to your test guild (kept) — full sync for all guilds occurs in on_ready
        gobj = discord.Object(id=self.TEST_GUILD_ID)
        self.tree.copy_global_to(guild=gobj)
        try:
            await self.tree.sync(guild=gobj)
        except Exception:
            pass

        # Start background tasks
        if not self.degrade_task.is_running():
            self.degrade_task.start()
        if not self.veteran_scan_task.is_running():
            self.veteran_scan_task.start()
        if not self.daily_warning_task.is_running():
            self.daily_warning_task.start()
        if not self.daily_survival_task.is_running():
            self.daily_survival_task.start()
        if not self.garden_refresh_task.is_running():
            self.garden_refresh_task.start()

    async def on_ready(self) -> None:
        print(f"Logged in as {self.user} (ID: {self.user.id})")
        # Auto-sync commands to all guilds on startup for immediate updates
        for g in self.guilds:
            try:
                self.tree.copy_global_to(guild=g)
                await self.tree.sync(guild=g)
            except Exception:
                pass
            await self.resync_guild_veterans(g)
            await self.ensure_garden_panel(g)
            await self.ensure_leaderboard_panel(g)
        # Announce online once per startup
        if not self._startup_announced:
            for g in self.guilds:
                await self.announce_status(g, online=True)
            self._startup_announced = True

    async def on_guild_join(self, guild: discord.Guild) -> None:
        # Ensure new guild gets the latest commands immediately
        self.tree.copy_global_to(guild=guild)
        try:
            await self.tree.sync(guild=guild)
        except Exception:
            pass
        await self.resync_guild_veterans(guild)
        await self.ensure_garden_panel(guild)
        await self.ensure_leaderboard_panel(guild)
        await self.announce_status(guild, online=True)

    async def close(self) -> None:
        # Best-effort offline announcement before shutting down
        if not self._closing_announced:
            for g in list(self.guilds):
                await self.announce_status(g, online=False)
            self._closing_announced = True
        await super().close()

    # ---------------- Rewards & Survival Counters ----------------
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

        # XP/coins with cooldown
        t = now_ts()
        if t - v.last_message_time >= self.config.get("message_cooldown_seconds", 60):
            v.last_message_time = t
            v.add_xp_coins(self.config.get("xp_per_message", 5), self.config.get("coins_per_message", 2))

        # Daily counter (Asia/Karachi)
        tz = ZoneInfo("Asia/Karachi")
        today_iso = datetime.now(tz).date().isoformat()
        if v.last_message_day_local != today_iso:
            v.last_message_day_local = today_iso
            v.messages_today = 0
        v.messages_today += 1

        self.save_all()

    # ---------------- Background Tasks ----------------
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
            # plant died: remove role
            for g in self.guilds:
                member = g.get_member(uid)
                if member:
                    role_id = self.config.get("veteran_role_id", 0)
                    role = g.get_role(role_id) if role_id else None
                    if role:
                        try:
                            await member.remove_roles(role, reason="Plant died (water depleted)")
                        except discord.Forbidden:
                            pass
            del self.veterans[uid]
            changed = True

        if changed:
            self.save_all()
            for g in self.guilds:
                await self.ensure_garden_panel(g)
                await self.ensure_leaderboard_panel(g)

    @tasks.loop(minutes=5.0)
    async def veteran_scan_task(self) -> None:
        for g in self.guilds:
            await self.resync_guild_veterans(g)

    @tasks.loop(minutes=5.0)
    async def garden_refresh_task(self) -> None:
        for g in self.guilds:
            await self.ensure_garden_panel(g)

    @tasks.loop(minutes=5.0)
    async def daily_warning_task(self) -> None:
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
                continue
            role_id = self.config.get("veteran_role_id", 0)
            role = guild.get_role(role_id) if role_id else None
            if not role:
                continue
            low = []
            for m in role.members:
                v = self.veterans.get(m.id)
                if v and v.water_level <= self.config.get("low_water_threshold", 20):
                    low.append(m)
            ping = f"<@&{role_id}> " if int(self.config.get("warn_ping_veteran_role", 1)) == 1 else ""
            content = (
                f"{ping}🌵 **Daily Water Warning** — Some plants are drying out! "
                f"Use **💧 Water My Plant** in the Garden."
            ) if low else f"{ping}🌿 **Daily Garden Reminder** — Keep chatting & watering."
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

    @tasks.loop(minutes=5.0)
    async def daily_survival_task(self) -> None:
        """
        Around local midnight (Asia/Karachi), check yesterday's message count.
        If < daily_min_messages, remove role and delete data.
        """
        tz = ZoneInfo("Asia/Karachi")
        now_local = datetime.now(tz)
        if not (now_local.hour == 0 and now_local.minute < 10):
            return
        min_msgs = int(self.config.get("daily_min_messages", 10))
        yesterday = (now_local.date() - timedelta(days=1)).isoformat()
        to_remove: List[int] = []
        for uid, v in list(self.veterans.items()):
            # If they didn't talk yesterday OR didn't hit threshold
            if v.last_message_day_local != yesterday or v.messages_today < min_msgs:
                to_remove.append(uid)

        if not to_remove:
            return

        for g in self.guilds:
            role_id = self.config.get("veteran_role_id", 0)
            role = g.get_role(role_id) if role_id else None
            for uid in to_remove:
                member = g.get_member(uid)
                if member and role:
                    try:
                        await member.remove_roles(role, reason=f"Did not send {min_msgs} msgs yesterday")
                    except discord.Forbidden:
                        pass

        for uid in to_remove:
            self.veterans.pop(uid, None)
        self.save_all()

        ch_id = int(self.config.get("garden_channel_id") or 0)
        if ch_id:
            for g in self.guilds:
                ch = g.get_channel(ch_id)
                if isinstance(ch, discord.TextChannel):
                    mentions = " ".join(f"<@{uid}>" for uid in to_remove)
                    try:
                        await ch.send(
                            f"💀 **Plants withered overnight** (under {min_msgs} messages yesterday): {mentions}"
                        )
                    except Exception:
                        pass

        for g in self.guilds:
            await self.ensure_garden_panel(g)
            await self.ensure_leaderboard_panel(g)


# ---------------- Entrypoint ----------------
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
