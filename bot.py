"""
Veteran Club Discord Bot
- Message-based XP/coins in configured channels
- Per-veteran private plant channel with BUTTONS (water, send coins, leaderboard)
- Plant water degrades over time; if it hits 0: remove Veteran role + delete channel
- Leaderboard and per-user stats
- Admin /configure to change settings at runtime

Requires: discord.py >= 2.1
"""

from __future__ import annotations

import json
import os
from typing import Dict, Optional, List, Any

from datetime import datetime, date, UTC

import discord
from discord.ext import commands, tasks


# ---------- Persistence ----------
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


# ---------- Model ----------
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
        self.channel_id: Optional[int] = data.get("channel_id")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "coins": self.coins,
            "xp": self.xp,
            "plant_start": self.plant_start,
            "water_level": self.water_level,
            "last_message_time": self.last_message_time,
            "coins_sent_today": self.coins_sent_today,
            "last_coins_reset": self.last_coins_reset,
            "channel_id": self.channel_id,
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


# ---------- Bot ----------
class VeteranBot(commands.Bot):
    TEST_GUILD_ID = 740784147798163508  # set to your guild

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
                "veteran_role_id": 0,
                "veteran_category_id": 0,
                "reward_channel_ids": [],
                "water_cost": 10,
                "plant_max_water": 100,
                "water_decrease_interval_minutes": 60,
                "water_decrease_amount": 1,
                "xp_per_message": 5,
                "coins_per_message": 2,
                "message_cooldown_seconds": 60,
                "max_coins_send_per_day": 100,
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

    # ---------- Utils ----------
    def save_all(self) -> None:
        save_json(DATA_FILE, {str(uid): v.to_dict() for uid, v in self.veterans.items()})

    # ---------- Views / Buttons (manual add_item; NO decorators) ----------
    def build_veteran_view(self, user_id: int) -> discord.ui.View:
        """
        Returns a persistent View with three buttons. We create Button objects,
        assign callbacks, and add them to the view. This guarantees buttons render.
        """
        view = discord.ui.View(timeout=None)
        bot = self  # capture for callbacks

        # Water Plant
        async def water_callback(inter: discord.Interaction):
            if inter.user.id != user_id:
                await inter.response.send_message("This isn’t your plant.", ephemeral=True)
                return
            v = bot.veterans.get(user_id)
            if not v:
                await inter.response.send_message("You are not registered.", ephemeral=True)
                return
            if v.water_plant():
                bot.save_all()
                embed = bot.build_stats_embed(inter.user, v)
                await inter.response.edit_message(embed=embed, view=bot.build_veteran_view(user_id))
                await inter.followup.send("Watered! 🌱", ephemeral=True)
            else:
                await inter.response.send_message("Not enough coins.", ephemeral=True)

        water_btn = discord.ui.Button(
            label="💧 Water Plant",
            style=discord.ButtonStyle.primary,
            custom_id=f"water:{user_id}",
        )
        water_btn.callback = water_callback
        view.add_item(water_btn)

        # Send Coins
        async def send_open_modal(inter: discord.Interaction):
            if inter.user.id != user_id:
                await inter.response.send_message("Use this on your own plant.", ephemeral=True)
                return
            if user_id not in bot.veterans:
                await inter.response.send_message("You are not registered.", ephemeral=True)
                return

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

                async def on_submit(self, modal_inter: discord.Interaction) -> None:
                    sender = bot.veterans.get(user_id)
                    if not sender:
                        await modal_inter.response.send_message("You are not registered.", ephemeral=True)
                        return

                    raw = self.recipient.value.replace("<@", "").replace("<@!", "").replace(">", "")
                    try:
                        target_id = int(raw)
                    except ValueError:
                        await modal_inter.response.send_message("Invalid user ID.", ephemeral=True)
                        return

                    try:
                        amt = int(self.amount.value)
                    except ValueError:
                        await modal_inter.response.send_message("Amount must be an integer.", ephemeral=True)
                        return

                    if amt <= 0:
                        await modal_inter.response.send_message("Amount must be positive.", ephemeral=True)
                        return
                    if target_id == user_id:
                        await modal_inter.response.send_message("You cannot send coins to yourself.", ephemeral=True)
                        return

                    target = bot.veterans.get(target_id)
                    if not target:
                        await modal_inter.response.send_message("Recipient is not a registered veteran.", ephemeral=True)
                        return

                    if not sender.can_send(amt):
                        await modal_inter.response.send_message(
                            "Cannot send that many coins (daily limit or insufficient funds).",
                            ephemeral=True,
                        )
                        return

                    sender.record_send(amt)
                    target.receive(amt)
                    bot.save_all()
                    await modal_inter.response.send_message(f"Sent {amt} coins to <@{target_id}>.", ephemeral=True)

            await inter.response.send_modal(SendCoinsModal())

        send_btn = discord.ui.Button(
            label="💸 Send Coins",
            style=discord.ButtonStyle.secondary,
            custom_id=f"send:{user_id}",
        )
        send_btn.callback = send_open_modal
        view.add_item(send_btn)

        # Leaderboard
        async def lb_callback(inter: discord.Interaction):
            await inter.response.defer(ephemeral=True)
            await bot.send_leaderboard(inter.channel)
            await inter.followup.send("Leaderboard posted.", ephemeral=True)

        lb_btn = discord.ui.Button(
            label="🏆 Leaderboard",
            style=discord.ButtonStyle.success,
            custom_id=f"lb:{user_id}",
        )
        lb_btn.callback = lb_callback
        view.add_item(lb_btn)

        return view

    # ---------- Embeds ----------
    def build_stats_embed(self, member: discord.Member | discord.User, v: VeteranData) -> discord.Embed:
        e = discord.Embed(title=f"{member.display_name}'s Plant", colour=discord.Colour.green())
        e.add_field(name="Level", value=str(v.level), inline=True)
        e.add_field(name="XP", value=str(v.xp), inline=True)
        e.add_field(name="Coins", value=str(v.coins), inline=True)
        e.add_field(name="Age (days)", value=f"{v.age_days:.1f}", inline=True)
        e.add_field(name="Water", value=f"{int(v.water_level)}/{self.config.get('plant_max_water', 100)}", inline=True)
        e.set_footer(text="Use the buttons below to interact with your plant.")
        return e

    # ---------- Channel/Role Helpers ----------
    async def get_or_create_veteran_channel(self, guild: discord.Guild, member: discord.Member) -> Optional[discord.TextChannel]:
        v = self.veterans.get(member.id)
        if v and v.channel_id:
            ch = guild.get_channel(v.channel_id)
            if isinstance(ch, discord.TextChannel):
                return ch

        cat_id = self.config.get("veteran_category_id", 0)
        if not cat_id:
            return None
        category = guild.get_channel(cat_id)
        if not isinstance(category, discord.CategoryChannel):
            return None

        name = f"{member.name}-plant"
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_messages=True),
        }
        ch = await guild.create_text_channel(
            name=name,
            category=category,
            overwrites=overwrites,
            topic=f"Private plant channel for {member.display_name}",
        )
        return ch

    async def create_veteran(self, member: discord.Member) -> None:
        v = VeteranData(member.id, {}, self.config)
        self.veterans[member.id] = v

        role_id = self.config.get("veteran_role_id", 0)
        if role_id:
            role = member.guild.get_role(role_id)
            if role:
                try:
                    await member.add_roles(role, reason="Registered as veteran")
                except discord.Forbidden:
                    pass

        ch = await self.get_or_create_veteran_channel(member.guild, member)
        if ch:
            v.channel_id = ch.id
            # Send panel WITH buttons
            await ch.send(embed=self.build_stats_embed(member, v), view=self.build_veteran_view(member.id))

        self.save_all()

    # ---------- Slash Commands & Sync ----------
    async def setup_hook(self) -> None:
        """Register slash commands, persistent views, and sync instantly to your guild."""

        @self.tree.command(name="configure", description="Configure bot settings (admin only)")
        @discord.app_commands.describe(setting="Setting to change", value="New value")
        async def configure(inter: discord.Interaction, setting: str, value: str):
            if not (inter.user.guild_permissions.manage_guild or inter.user.guild_permissions.administrator):
                await inter.response.send_message("You do not have permission to configure the bot.", ephemeral=True)
                return

            key = setting
            if key in {
                "veteran_role_id",
                "veteran_category_id",
                "water_cost",
                "plant_max_water",
                "water_decrease_interval_minutes",
                "water_decrease_amount",
                "xp_per_message",
                "coins_per_message",
                "message_cooldown_seconds",
                "max_coins_send_per_day",
            }:
                try:
                    self.config[key] = int(value)
                except ValueError:
                    await inter.response.send_message(f"Expected integer value for {key}.", ephemeral=True)
                    return
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
            for v in self.veterans.values():
                v.config = self.config
            await inter.response.send_message(f"Configuration `{key}` updated to `{value}`.", ephemeral=True)

        @self.tree.command(name="register", description="Register a member as a veteran and create their channel")
        @discord.app_commands.describe(member="Member to register")
        async def register_member(inter: discord.Interaction, member: discord.Member):
            if not (inter.user.guild_permissions.manage_guild or inter.user.guild_permissions.administrator):
                await inter.response.send_message("You do not have permission to register veterans.", ephemeral=True)
                return
            if member.id in self.veterans:
                await inter.response.send_message(f"{member.display_name} is already registered.", ephemeral=True)
                return
            await self.create_veteran(member)
            await inter.response.send_message(f"Registered {member.display_name} as a veteran.", ephemeral=True)

        @self.tree.command(name="leaderboard", description="Show the veteran leaderboard")
        async def leaderboard(inter: discord.Interaction):
            await self.send_leaderboard(inter.channel)
            await inter.response.send_message("Leaderboard sent.", ephemeral=True)

        @self.tree.command(name="mystats", description="Show your plant stats")
        async def mystats(inter: discord.Interaction):
            v = self.veterans.get(inter.user.id)
            if not v:
                await inter.response.send_message("You are not registered as a veteran.", ephemeral=True)
                return
            embed = self.build_stats_embed(inter.user, v)
            await inter.response.send_message(embed=embed, view=self.build_veteran_view(inter.user.id), ephemeral=True)

        # Re-register persistent views (so buttons work after restart)
        for uid in list(self.veterans.keys()):
            self.add_view(self.build_veteran_view(uid))

        # Instant sync to your specific guild
        test_guild = discord.Object(id=self.TEST_GUILD_ID)
        self.tree.copy_global_to(guild=test_guild)
        await self.tree.sync(guild=test_guild)

        # Start background loop AFTER loop exists
        if not self.degrade_task.is_running():
            self.degrade_task.start()

    async def on_guild_join(self, guild: discord.Guild) -> None:
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)

    async def on_ready(self) -> None:
        print(f"Logged in as {self.user} (ID: {self.user.id})")
        print("------")

    # ---------- Rewards ----------
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if message.channel.id not in self.config.get("reward_channel_ids", []):
            return
        v = self.veterans.get(message.author.id)
        if not v:
            return

        t = now_ts()
        if t - v.last_message_time < self.config.get("message_cooldown_seconds", 60):
            return

        v.last_message_time = t
        v.add_xp_coins(
            self.config.get("xp_per_message", 5),
            self.config.get("coins_per_message", 2),
        )
        self.save_all()

    # ---------- Background Plant Degrade ----------
    @tasks.loop(minutes=1.0)
    async def degrade_task(self) -> None:
        t = now_ts()
        interval = self.config.get("water_decrease_interval_minutes", 60) * 60

        # Throttle
        if not hasattr(self.degrade_task, "last"):
            setattr(self.degrade_task, "last", t)
            return
        last = getattr(self.degrade_task, "last")
        if t - last < interval:
            return
        setattr(self.degrade_task, "last", t)

        # Degrade all; remove dead
        changed = False
        for uid, v in list(self.veterans.items()):
            v.degrade()
            if v.is_alive():
                continue

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
                if v.channel_id:
                    ch = g.get_channel(v.channel_id)
                    if isinstance(ch, discord.TextChannel):
                        try:
                            await ch.delete(reason="Plant died")
                        except discord.Forbidden:
                            pass

            del self.veterans[uid]
            changed = True

        if changed:
            self.save_all()


# ---------- Entrypoint ----------
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
