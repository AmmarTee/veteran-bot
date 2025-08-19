"""
Veteran Club Discord Bot (Per-Veteran Channels; Owner-Only Actions; Daily Leaderboard Refresh)

- Auto-detects veterans by role; no manual /register.
- Creates one channel per veteran in the configured category.
- All veterans can SEE every veteran channel; ONLY the owner can Water/Send from their panel.
- Earn coins/XP in configured reward channels.
- Plant degrades; on death => remove Veteran role + delete the veteran’s channel and panel.
- Persistent buttons across restarts.
- Admin commands: /configure, /leaderboard, /mystats, /resync_veterans.
- NEW: “🔄 Update Leaderboard (1/day)” button on every panel:
  * Any veteran can press it, in any veteran channel.
  * Posts the leaderboard in that channel.
  * Per-veteran cooldown: once per UTC day.

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
        self.panel_message_id: Optional[int] = data.get("panel_message_id")

        # NEW: per-veteran daily limit for pressing the leaderboard refresh button
        self.last_lb_refresh: str = data.get("last_lb_refresh", "")  # ISO YYYY-MM-DD

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
            "panel_message_id": self.panel_message_id,
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


# ---------- Bot ----------
class VeteranBot(commands.Bot):
    TEST_GUILD_ID = 740784147798163508  # set to your guild for instant command sync

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
                "veteran_role_id": 0,                # role that marks veterans
                "veteran_category_id": 0,            # category for per-veteran channels
                "reward_channel_ids": [],            # channels where chat earns XP/coins
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

    def build_stats_embed(self, member: discord.Member | discord.User, v: VeteranData) -> discord.Embed:
        e = discord.Embed(title=f"{member.display_name}'s Plant", colour=discord.Colour.green())
        e.add_field(name="Level", value=str(v.level), inline=True)
        e.add_field(name="XP", value=str(v.xp), inline=True)
        e.add_field(name="Coins", value=str(v.coins), inline=True)
        e.add_field(name="Age (days)", value=f"{v.age_days:.1f}", inline=True)
        e.add_field(name="Water", value=f"{int(v.water_level)}/{self.config.get('plant_max_water', 100)}", inline=True)
        e.set_footer(text="Use the buttons below to interact with your plant.")
        return e

    def build_leaderboard_embed(self) -> discord.Embed:
        embed = discord.Embed(title="Veteran Leaderboard", colour=discord.Colour.gold())
        if not self.veterans:
            embed.description = "No veterans detected yet."
            return embed
        sorted_members = sorted(self.veterans.items(), key=lambda kv: (-kv[1].age_days, -kv[1].xp))
        lines = []
        for idx, (user_id, vdata) in enumerate(sorted_members[:20], start=1):
            lines.append(
                f"**{idx}. <@{user_id}>** – Level {vdata.level}, XP {vdata.xp}, "
                f"Age {vdata.age_days:.1f}d, Coins {vdata.coins}"
            )
        embed.description = "\n".join(lines)
        return embed

    # ---------- Views / Buttons (owner-gated actions + daily LB refresh) ----------
    def build_veteran_view(self, owner_id: int) -> discord.ui.View:
        """
        Buttons created explicitly and added to the View; stable custom_ids.
        Only the owner (owner_id) can Water/Send; others see but get denied on press.
        Any veteran can press the daily leaderboard refresh (once per UTC day).
        """
        view = discord.ui.View(timeout=None)
        bot = self

        # Water Plant (owner-only)
        async def water_callback(inter: discord.Interaction):
            if inter.user.id != owner_id:
                await inter.response.send_message("Only the plant owner can water this plant.", ephemeral=True)
                return
            v = bot.veterans.get(owner_id)
            if not v:
                await inter.response.send_message("No plant data found.", ephemeral=True)
                return
            if v.water_plant():
                bot.save_all()
                member = inter.guild.get_member(owner_id) if inter.guild else inter.user
                embed = bot.build_stats_embed(member, v)
                try:
                    await inter.response.edit_message(embed=embed, view=bot.build_veteran_view(owner_id))
                except discord.InteractionResponded:
                    await inter.followup.edit_message(inter.message.id, embed=embed, view=bot.build_veteran_view(owner_id))
                await inter.followup.send("Watered! 🌱", ephemeral=True)
            else:
                await inter.response.send_message("Not enough coins.", ephemeral=True)

        water_btn = discord.ui.Button(label="💧 Water Plant", style=discord.ButtonStyle.primary, custom_id=f"water:{owner_id}")
        water_btn.callback = water_callback
        view.add_item(water_btn)

        # Send Coins (owner-only; opens modal)
        async def send_open_modal(inter: discord.Interaction):
            if inter.user.id != owner_id:
                await inter.response.send_message("Only the plant owner can send coins from this panel.", ephemeral=True)
                return
            if owner_id not in bot.veterans:
                await inter.response.send_message("No plant data found.", ephemeral=True)
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
                    sender = bot.veterans.get(owner_id)
                    if not sender:
                        await modal_inter.response.send_message("No plant data found.", ephemeral=True)
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
                    if target_id == owner_id:
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

        send_btn = discord.ui.Button(label="💸 Send Coins", style=discord.ButtonStyle.secondary, custom_id=f"send:{owner_id}")
        send_btn.callback = send_open_modal
        view.add_item(send_btn)

        # NEW: Daily Leaderboard Refresh (any veteran; 1/day)
        async def refresh_lb_callback(inter: discord.Interaction):
            # Must be a veteran
            role_id = bot.config.get("veteran_role_id", 0)
            if not role_id or not inter.guild:
                await inter.response.send_message("Leaderboard refresh is not available.", ephemeral=True)
                return
            if not any(r.id == role_id for r in inter.user.roles):
                await inter.response.send_message("Only veterans can refresh the leaderboard.", ephemeral=True)
                return

            # Ensure we have a VeteranData record for the pressing user
            pressing = bot.veterans.get(inter.user.id)
            if not pressing:
                pressing = VeteranData(inter.user.id, {}, bot.config)
                bot.veterans[inter.user.id] = pressing

            today = date.today().isoformat()  # UTC-based midnight boundary
            if pressing.last_lb_refresh == today:
                await inter.response.send_message("You’ve already refreshed the leaderboard today. Try again tomorrow.", ephemeral=True)
                return

            # Update cooldown and post the leaderboard in this channel
            pressing.last_lb_refresh = today
            bot.save_all()

            # Permission sanity
            if isinstance(inter.channel, discord.abc.GuildChannel):
                perms = inter.channel.permissions_for(inter.guild.me)
                if not perms.send_messages:
                    await inter.response.send_message("I can't send messages in this channel.", ephemeral=True)
                    return
                if not perms.embed_links:
                    await inter.response.send_message("I need **Embed Links** permission here.", ephemeral=True)
                    return

            await inter.response.send_message(embed=bot.build_leaderboard_embed())  # public

        refresh_btn = discord.ui.Button(
            label="🔄 Update Leaderboard (1/day)",
            style=discord.ButtonStyle.success,
            custom_id=f"lb:refresh:{owner_id}",
        )
        refresh_btn.callback = refresh_lb_callback
        view.add_item(refresh_btn)

        return view

    # ---------- Channel/Role Helpers ----------
    async def get_or_create_veteran_channel(self, guild: discord.Guild, member: discord.Member) -> Optional[discord.TextChannel]:
        """Create/fetch the veteran's channel under category; visible to all veterans, private from others."""
        v = self.veterans.get(member.id)
        if v and v.channel_id:
            ch = guild.get_channel(v.channel_id)
            if isinstance(ch, discord.TextChannel):
                return ch

        cat_id = self.config.get("veteran_category_id", 0)
        role_id = self.config.get("veteran_role_id", 0)
        if not cat_id or not role_id:
            return None

        category = guild.get_channel(cat_id)
        if not isinstance(category, discord.CategoryChannel):
            return None

        veteran_role = guild.get_role(role_id)
        if not veteran_role:
            return None

        name = f"🌱-{member.name}".lower().replace(" ", "-")
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            veteran_role: discord.PermissionOverwrite(view_channel=True, read_message_history=True, send_messages=True),
            member: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_messages=True, manage_channels=True),
        }

        ch = await guild.create_text_channel(
            name=name,
            category=category,
            overwrites=overwrites,
            topic=f"Plant channel for {member.display_name} (visible to all Veterans; owner-only actions).",
        )
        return ch

    async def ensure_panel_in_channel(self, channel: discord.TextChannel, owner: discord.Member) -> None:
        """Ensure there is a panel message with buttons in the owner’s channel."""
        v = self.veterans.get(owner.id)
        if not v:
            v = VeteranData(owner.id, {}, self.config)
            self.veterans[owner.id] = v

        embed = self.build_stats_embed(owner, v)
        view = self.build_veteran_view(owner.id)

        if v.panel_message_id:
            try:
                msg = await channel.fetch_message(v.panel_message_id)
            except Exception:
                v.panel_message_id = None
            else:
                await msg.edit(embed=embed, view=view)
                return

        msg = await channel.send(embed=embed, view=view)
        v.panel_message_id = msg.id
        v.channel_id = channel.id
        self.save_all()

    async def delete_veteran_channel(self, guild: discord.Guild, user_id: int) -> None:
        v = self.veterans.get(user_id)
        if not v or not v.channel_id:
            return
        ch = guild.get_channel(v.channel_id)
        if isinstance(ch, discord.TextChannel):
            try:
                await ch.delete(reason="Plant died")
            except discord.Forbidden:
                pass
        v.channel_id = None
        v.panel_message_id = None
        self.save_all()

    async def resync_guild_veterans(self, guild: discord.Guild) -> None:
        """Scan veteran role, ensure per-veteran channels & panels; remove channels for those who lost the role."""
        role_id = self.config.get("veteran_role_id", 0)
        if not role_id:
            return
        role = guild.get_role(role_id)
        if not role:
            return

        should_be = set(m.id for m in role.members)

        # Ensure channels and panels for all current veterans
        for member in role.members:
            ch = await self.get_or_create_veteran_channel(guild, member)
            if ch:
                await self.ensure_panel_in_channel(ch, member)

        # Remove channels for users who lost the role
        for uid, v in list(self.veterans.items()):
            if uid not in should_be and v.channel_id:
                await self.delete_veteran_channel(guild, uid)
                self.veterans.pop(uid, None)
        self.save_all()

    # ---------- Slash Commands & Sync ----------
    async def setup_hook(self) -> None:
        """Register slash commands, persistent views, and sync instantly to your guild."""

        @self.tree.command(name="configure", description="Configure bot settings (admin only)")
        @discord.app_commands.describe(setting="Setting to change", value="New value (IDs as integers; comma list for reward_channel_ids)")
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
            await inter.response.send_message(f"Configuration `{key}` updated to `{value}`.", ephemeral=True)

        @self.tree.command(name="leaderboard", description="Show the veteran leaderboard")
        async def leaderboard(inter: discord.Interaction):
            # Permission sanity
            if inter.guild and isinstance(inter.channel, discord.abc.GuildChannel):
                perms = inter.channel.permissions_for(inter.guild.me)
                if not perms.send_messages:
                    await inter.response.send_message("I can't send messages in this channel.", ephemeral=True)
                    return
                if not perms.embed_links:
                    await inter.response.send_message("I need the **Embed Links** permission here.", ephemeral=True)
                    return
            await inter.response.send_message(embed=self.build_leaderboard_embed())

        @self.tree.command(name="mystats", description="Show your plant stats")
        async def mystats(inter: discord.Interaction):
            v = self.veterans.get(inter.user.id)
            if not v:
                await inter.response.send_message("No plant data yet. If you have the Veteran role, an admin can run /resync_veterans.", ephemeral=True)
                return
            embed = self.build_stats_embed(inter.user, v)
            await inter.response.send_message(embed=embed, view=self.build_veteran_view(inter.user.id), ephemeral=True)

        @self.tree.command(name="resync_veterans", description="Scan the Veteran role and rebuild channels/panels (admin only)")
        async def resync_veterans(inter: discord.Interaction):
            if not (inter.user.guild_permissions.manage_guild or inter.user.guild_permissions.administrator):
                await inter.response.send_message("You do not have permission.", ephemeral=True)
                return
            await inter.response.defer(ephemeral=True)  # <- important
            await self.resync_guild_veterans(inter.guild)
            await inter.followup.send("Resynced veteran channels and panels.")


        # Re-register persistent views for all known veterans (so buttons work after restart)
        for uid in list(self.veterans.keys()):
            self.add_view(self.build_veteran_view(uid))

        # Instant sync to your specific guild
        test_guild = discord.Object(id=self.TEST_GUILD_ID)
        self.tree.copy_global_to(guild=test_guild)
        await self.tree.sync(guild=test_guild)

        # Start loops after event loop exists
        if not self.degrade_task.is_running():
            self.degrade_task.start()
        if not self.veteran_scan_task.is_running():
            self.veteran_scan_task.start()

    async def on_ready(self) -> None:
        print(f"Logged in as {self.user} (ID: {self.user.id})")
        print("------")
        # Initial resync on boot
        for g in self.guilds:
            await self.resync_guild_veterans(g)

    async def on_guild_join(self, guild: discord.Guild) -> None:
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        await self.resync_guild_veterans(guild)

    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        """React to veteran role grant/removal to maintain channels automatically."""
        role_id = self.config.get("veteran_role_id", 0)
        if not role_id:
            return
        had = any(r.id == role_id for r in before.roles)
        has = any(r.id == role_id for r in after.roles)
        if not had and has:
            ch = await self.get_or_create_veteran_channel(after.guild, after)
            if ch:
                await self.ensure_panel_in_channel(ch, after)
        elif had and not has:
            await self.delete_veteran_channel(after.guild, after.id)
            self.veterans.pop(after.id, None)
            self.save_all()

    # ---------- Rewards ----------
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return
        if message.channel.id not in self.config.get("reward_channel_ids", []):
            return

        # Reward only veterans (by role), auto-create data if missing
        role_id = self.config.get("veteran_role_id", 0)
        if not role_id or not discord.utils.get(message.author.roles, id=role_id):
            return

        v = self.veterans.get(message.author.id)
        if not v:
            v = VeteranData(message.author.id, {}, self.config)
            self.veterans[message.author.id] = v
            # Ensure they have a channel/panel
            ch = await self.get_or_create_veteran_channel(message.guild, message.author)
            if ch:
                await self.ensure_panel_in_channel(ch, message.author)

        t = now_ts()
        if t - v.last_message_time < self.config.get("message_cooldown_seconds", 60):
            return
        v.last_message_time = t
        v.add_xp_coins(self.config.get("xp_per_message", 5), self.config.get("coins_per_message", 2))
        self.save_all()

    # ---------- Background Tasks ----------
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

            # Plant died: remove role + delete channel
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
                await self.delete_veteran_channel(g, uid)

            del self.veterans[uid]
            changed = True

        if changed:
            self.save_all()

    @tasks.loop(minutes=5.0)
    async def veteran_scan_task(self) -> None:
        """Safety net: rescan veteran role to keep channels/panels in sync."""
        for g in self.guilds:
            await self.resync_guild_veterans(g)


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
