"""
Discord bot that manages a simple gamified “veteran club” experience
using message‑based XP/coin rewards, plant watering mechanics and
leaderboards.

This bot is designed to keep veteran members engaged in a dedicated
channel by rewarding them for chatting, allowing them to grow a virtual
plant and compete on a leaderboard.  When a member joins the veteran
club they are given their own private channel (under a configured
category) with a persistent message containing buttons for common
actions such as watering the plant, viewing their stats and sending
coins to another veteran.  As members chat they accrue XP and coins,
which can be spent on watering the plant.  Failing to water the plant
within a configurable time window will cause the plant to die and the
member will automatically lose the veteran role.

Persisted data (coins, XP, plant ages, water levels and daily send
limits) are stored in a JSON file.  Guild specific configuration
options are stored in a separate JSON file.  You can edit the
configuration file or use the provided slash commands to change
settings while the bot is running.

**Important:** This script depends on the `discord.py` library (v2.1 or
newer) which adds support for components such as buttons and slash
commands.  The official `discord.py` documentation notes that
buttons and other interactions are available starting with the 2.0
release; earlier versions and third party libraries like
`discord‑components` are no longer recommended【702007078965881†L1006-L1086】.  If the
library is not installed the bot will fail to run – please refer to
the accompanying README.md for installation instructions.

Usage:
    1.  Install dependencies (see README.md).
    2.  Create a Discord application and bot user at https://discord.com/developers/applications.
    3.  Copy your bot token into an environment variable called DISCORD_TOKEN or
        place it in a `.env` file alongside this script (see README).
    4.  Adjust `config.json` to match your server (IDs for the veteran role,
        veteran category and reward channels).
    5.  Run the bot with `python bot.py`.
"""

from __future__ import annotations

import asyncio
import json
import os
import datetime
from typing import Dict, Optional, List, Any

import discord
from discord.ext import commands, tasks


# Paths to persistent data files.  These files live in the same directory
# as this script.  If they do not exist they will be created on first run.
DATA_FILE = os.path.join(os.path.dirname(__file__), "data.json")
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")


def load_json(path: str, default: Any) -> Any:
    """Load JSON from a file or return a default value if it does not exist."""
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            # If loading fails return default but preserve corrupt file for debugging
            return default
    return default


def save_json(path: str, data: Any) -> None:
    """Write JSON to a file atomically."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
    os.replace(tmp, path)


def get_now() -> float:
    """Return current UTC timestamp as float."""
    return datetime.datetime.utcnow().timestamp()


class VeteranData:
    """Encapsulates per‑veteran state and persistence.

    Attributes stored for each veteran member include:

    - `coins`: current currency balance.
    - `xp`: total experience points earned by chatting.
    - `plant_start`: timestamp when the plant was created or last revived.
    - `water_level`: current water meter (decreases over time).
    - `last_message_time`: timestamp of the last message used for XP/coin reward to prevent spamming.
    - `coins_sent_today`: total coins sent to others in the current day.
    - `last_coins_reset`: date (ISO) when the daily send limit was last reset.
    - `channel_id`: the ID of the private channel for the veteran.
    """

    def __init__(self, user_id: int, data: Dict[str, Any], config: Dict[str, Any]):
        self.user_id = user_id
        # Load fields or set defaults
        self.coins: int = data.get("coins", 0)
        self.xp: int = data.get("xp", 0)
        self.plant_start: float = data.get("plant_start", get_now())
        self.water_level: float = data.get("water_level", config.get("plant_max_water", 100))
        self.last_message_time: float = data.get("last_message_time", 0.0)
        self.coins_sent_today: int = data.get("coins_sent_today", 0)
        self.last_coins_reset: str = data.get("last_coins_reset", datetime.date.today().isoformat())
        self.channel_id: Optional[int] = data.get("channel_id")
        self.config = config

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

    def add_xp_and_coins(self, xp_amount: int, coin_amount: int) -> None:
        """Increase XP and coins for the member."""
        self.xp += xp_amount
        self.coins += coin_amount

    @property
    def age_days(self) -> float:
        """Return the number of days since the plant was created."""
        return (get_now() - self.plant_start) / 86400

    @property
    def level(self) -> int:
        """Compute plant level based on XP using a simple formula (sqrt scaling)."""
        return int((self.xp / 10) ** 0.5) + 1

    def reset_daily_limit(self) -> None:
        """Reset daily coin sending limit if a new day has started."""
        today = datetime.date.today().isoformat()
        if self.last_coins_reset != today:
            self.coins_sent_today = 0
            self.last_coins_reset = today

    def can_send(self, amount: int) -> bool:
        """Determine whether the member can send the given amount of coins today."""
        self.reset_daily_limit()
        return (self.coins_sent_today + amount) <= self.config.get("max_coins_send_per_day", 100) and self.coins >= amount

    def record_send(self, amount: int) -> None:
        """Record that the member sent `amount` coins today."""
        self.reset_daily_limit()
        self.coins_sent_today += amount
        self.coins -= amount

    def receive(self, amount: int) -> None:
        """Increase the member's coins by `amount`."""
        self.coins += amount

    def water_plant(self) -> bool:
        """Water the plant if the member can afford it.  Returns True on success."""
        cost = self.config.get("water_cost", 10)
        max_water = self.config.get("plant_max_water", 100)
        if self.coins >= cost:
            self.coins -= cost
            self.water_level = max_water
            return True
        return False

    def degrade(self) -> None:
        """Decrease water level by configured amount."""
        self.water_level -= self.config.get("water_decrease_amount", 1)

    def is_alive(self) -> bool:
        """Return True if plant has water remaining."""
        return self.water_level > 0


class VeteranBot(commands.Bot):
    """Main bot class implementing veteran club functionality."""

    def __init__(self, **kwargs: Any) -> None:
        intents = discord.Intents.default()
        # We need message content and guild/member events to function
        intents.message_content = True
        intents.messages = True
        intents.members = True
        intents.guilds = True
        super().__init__(intents=intents, **kwargs)

        # Load persistent state and configuration
        self.data: Dict[str, Dict[str, Any]] = load_json(DATA_FILE, {})
        self.config: Dict[str, Any] = load_json(CONFIG_FILE, {
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
        })
        self.veterans: Dict[int, VeteranData] = {}
        # Load existing veteran state
        for user_id_str, vdata in self.data.items():
            try:
                user_id_int = int(user_id_str)
                self.veterans[user_id_int] = VeteranData(user_id_int, vdata, self.config)
            except ValueError:
                continue

        # Start background task to degrade water
        self.degrade_task.start()

    async def setup_hook(self) -> None:
        """Register commands during setup."""
        # Register slash commands here
        @self.tree.command(name="configure", description="Configure bot settings (admin only)")
        @discord.app_commands.describe(setting="Name of the setting to change", value="New value")
        async def configure(interaction: discord.Interaction, setting: str, value: str):
            """Administrative slash command to change configuration values.

            Only users with administrator or manage guild permission may use this
            command.  Supported settings include veteran_role_id,
            veteran_category_id, reward_channel_ids, water_cost, plant_max_water,
            water_decrease_interval_minutes, water_decrease_amount,
            xp_per_message, coins_per_message, message_cooldown_seconds and
            max_coins_send_per_day.  Channels and roles can be supplied as
            mentions or by raw IDs.
            """
            # Permission check
            if not interaction.user.guild_permissions.manage_guild and not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message("You do not have permission to configure the bot.", ephemeral=True)
                return
            key = setting
            # Attempt to parse int for numeric settings or channel/role IDs
            if key in {"veteran_role_id", "veteran_category_id", "water_cost", "plant_max_water", "water_decrease_interval_minutes", "water_decrease_amount", "xp_per_message", "coins_per_message", "message_cooldown_seconds", "max_coins_send_per_day"}:
                try:
                    self.config[key] = int(value)
                except ValueError:
                    await interaction.response.send_message(f"Expected integer value for {key}.", ephemeral=True)
                    return
            elif key == "reward_channel_ids":
                # Accept a comma separated list of channel mentions or IDs
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
                await interaction.response.send_message(f"Unknown setting: {key}", ephemeral=True)
                return
            # Persist configuration
            save_json(CONFIG_FILE, self.config)
            # Propagate new config to VeteranData instances
            for v in self.veterans.values():
                v.config = self.config
            await interaction.response.send_message(f"Configuration `{key}` updated to `{value}`.", ephemeral=True)

        @self.tree.command(name="register", description="Manually register a member as a veteran")
        @discord.app_commands.describe(member="The member to register")
        async def register_member(interaction: discord.Interaction, member: discord.Member):
            """Slash command for admins to register a member as a veteran and create their channel."""
            if not interaction.user.guild_permissions.manage_guild and not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message("You do not have permission to register veterans.", ephemeral=True)
                return
            if member.id in self.veterans:
                await interaction.response.send_message(f"{member.display_name} is already registered.", ephemeral=True)
                return
            await self.create_veteran(member)
            await interaction.response.send_message(f"Registered {member.display_name} as a veteran.", ephemeral=True)

        @self.tree.command(name="leaderboard", description="Show the veteran leaderboard")
        async def leaderboard(interaction: discord.Interaction):
            """Send an embed with the top veterans by plant age and XP."""
            await self.send_leaderboard(interaction.channel)
            await interaction.response.send_message("Sent leaderboard.", delete_after=0)

        @self.tree.command(name="mystats", description="Show your plant stats")
        async def mystats(interaction: discord.Interaction):
            """Send an embed with the caller's plant stats."""
            vdata = self.veterans.get(interaction.user.id)
            if not vdata:
                await interaction.response.send_message("You are not registered as a veteran.", ephemeral=True)
                return
            embed = self.build_stats_embed(interaction.user, vdata)
            await interaction.response.send_message(embed=embed, view=self.build_veteran_view(interaction.user.id), delete_after=0)

        # Sync commands to all guilds this bot is a member of
        await self.tree.sync()

    async def on_ready(self) -> None:
        print(f"Logged in as {self.user} (ID: {self.user.id})")
        print("------")

    async def get_or_create_veteran_channel(self, guild: discord.Guild, member: discord.Member) -> Optional[discord.TextChannel]:
        """Create a dedicated channel for the veteran under the configured category.

        The channel is private to the member and server administrators.  If a
        channel already exists (based on persisted state) it is fetched and
        returned.
        """
        vdata = self.veterans.get(member.id)
        # If channel already recorded, fetch it
        if vdata and vdata.channel_id:
            channel = guild.get_channel(vdata.channel_id)
            if channel:
                return channel
        # Otherwise create a new channel
        category_id = self.config.get("veteran_category_id")
        if not category_id:
            return None
        category = guild.get_channel(category_id)
        if not isinstance(category, discord.CategoryChannel):
            return None
        # Channel name based on member name
        safe_name = f"{member.name}-plant"
        # Overwrites: allow member and admins to view, deny others
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_messages=True),
        }
        channel = await guild.create_text_channel(name=safe_name, category=category, overwrites=overwrites, topic=f"Private plant channel for {member.display_name}")
        return channel

    async def create_veteran(self, member: discord.Member) -> None:
        """Create the veteran data entry and private channel for a new veteran."""
        # Create data object
        vdata = VeteranData(member.id, {}, self.config)
        # Save to dict
        self.veterans[member.id] = vdata
        # Add veteran role
        veteran_role_id = self.config.get("veteran_role_id")
        if veteran_role_id:
            role = member.guild.get_role(veteran_role_id)
            if role:
                try:
                    await member.add_roles(role, reason="Registered as veteran")
                except discord.Forbidden:
                    pass
        # Create channel
        channel = await self.get_or_create_veteran_channel(member.guild, member)
        if channel:
            vdata.channel_id = channel.id
            # Send initial message with buttons
            await channel.send(embed=self.build_stats_embed(member, vdata), view=self.build_veteran_view(member.id))
        # Persist data
        self.save_data()

    def build_stats_embed(self, member: discord.Member, vdata: VeteranData) -> discord.Embed:
        """Build an embed showing the member's plant stats."""
        embed = discord.Embed(title=f"{member.display_name}'s Plant", colour=discord.Colour.green())
        embed.add_field(name="Level", value=str(vdata.level), inline=True)
        embed.add_field(name="XP", value=str(vdata.xp), inline=True)
        embed.add_field(name="Coins", value=str(vdata.coins), inline=True)
        embed.add_field(name="Age (days)", value=f"{vdata.age_days:.1f}", inline=True)
        embed.add_field(name="Water", value=f"{int(vdata.water_level)}/{self.config.get('plant_max_water', 100)}", inline=True)
        embed.set_footer(text="Use the buttons below to interact with your plant!")
        return embed

    def build_veteran_view(self, user_id: int) -> discord.ui.View:
        """Return a View with buttons for watering, sending coins and showing leaderboard."""
        view = discord.ui.View(timeout=None)

        # Water button
        @discord.ui.button(label="Water Plant", style=discord.ButtonStyle.primary, custom_id=f"water_{user_id}")
        async def water_button(interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id != user_id:
                await interaction.response.send_message("This is not your plant.", ephemeral=True)
                return
            vdata = self.veterans.get(user_id)
            if not vdata:
                await interaction.response.send_message("You are not registered.", ephemeral=True)
                return
            if vdata.water_plant():
                # Save and update message
                self.save_data()
                embed = self.build_stats_embed(interaction.user, vdata)
                await interaction.response.edit_message(embed=embed, view=self.build_veteran_view(user_id))
                await interaction.followup.send("You watered your plant!", ephemeral=True)
            else:
                await interaction.response.send_message("You don't have enough coins to buy water.", ephemeral=True)

        # Send coins button
        @discord.ui.button(label="Send Coins", style=discord.ButtonStyle.secondary, custom_id=f"send_{user_id}")
        async def send_button(interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id != user_id:
                await interaction.response.send_message("You can only use this from your own plant channel.", ephemeral=True)
                return
            vdata = self.veterans.get(user_id)
            if not vdata:
                await interaction.response.send_message("You are not registered.", ephemeral=True)
                return
            # Present a modal to choose recipient and amount
            class SendCoinsModal(discord.ui.Modal, title="Send Coins"):
                recipient = discord.ui.TextInput(label="Recipient ID", placeholder="Enter user ID or mention", required=True)
                amount = discord.ui.TextInput(label="Amount", placeholder="Number of coins", required=True)

                async def on_submit(self, modal_interaction: discord.Interaction) -> None:
                    # Parse recipient
                    target_id_raw = self.recipient.value.replace("<@", "").replace("<@!", "").replace(">", "")
                    try:
                        target_id = int(target_id_raw)
                    except ValueError:
                        await modal_interaction.response.send_message("Invalid user ID.", ephemeral=True)
                        return
                    try:
                        amount_int = int(self.amount.value)
                    except ValueError:
                        await modal_interaction.response.send_message("Amount must be an integer.", ephemeral=True)
                        return
                    if amount_int <= 0:
                        await modal_interaction.response.send_message("Amount must be positive.", ephermal=True)
                        return
                    if target_id == user_id:
                        await modal_interaction.response.send_message("You cannot send coins to yourself.", ephermal=True)
                        return
                    # Find recipient veteran
                    target_vdata = self.veterans.get(target_id)
                    if not target_vdata:
                        await modal_interaction.response.send_message("Recipient is not a registered veteran.", ephermal=True)
                        return
                    # Check sender can send
                    if not vdata.can_send(amount_int):
                        await modal_interaction.response.send_message("You cannot send that many coins (daily limit or insufficient funds).", ephermal=True)
                        return
                    # Perform transfer
                    vdata.record_send(amount_int)
                    target_vdata.receive(amount_int)
                    self.save_data()
                    await modal_interaction.response.send_message(f"Sent {amount_int} coins to <@{target_id}>!", ephermal=True)

            modal = SendCoinsModal()
            await interaction.response.send_modal(modal)

        # Leaderboard button
        @discord.ui.button(label="Leaderboard", style=discord.ButtonStyle.success, custom_id=f"leaderboard_{user_id}")
        async def leaderboard_button(interaction: discord.Interaction, button: discord.ui.Button):
            await interaction.response.defer(ephemeral=True)
            await self.send_leaderboard(interaction.channel)
            await interaction.followup.send("Leaderboard sent.", ephermal=True)

        return view

    async def send_leaderboard(self, channel: discord.abc.Messageable) -> None:
        """Send an embed leaderboard sorted by plant age and XP."""
        if not self.veterans:
            await channel.send("No veterans registered yet.")
            return
        # Sort by descending age
        sorted_members = sorted(self.veterans.items(), key=lambda kv: (-kv[1].age_days, -kv[1].xp))
        embed = discord.Embed(title="Veteran Leaderboard", colour=discord.Colour.gold())
        description_lines: List[str] = []
        for idx, (user_id, vdata) in enumerate(sorted_members[:20], start=1):
            member_mention = f"<@{user_id}>"
            description_lines.append(f"**{idx}. {member_mention}** – Level {vdata.level}, XP {vdata.xp}, Age {vdata.age_days:.1f}d, Coins {vdata.coins}")
        embed.description = "\n".join(description_lines)
        await channel.send(embed=embed)

    async def on_message(self, message: discord.Message) -> None:
        """Award XP and coins for messages in configured reward channels and handle registration events."""
        # Ignore messages from bots
        if message.author.bot:
            return
        # Only reward in configured channels
        if message.channel.id not in self.config.get("reward_channel_ids", []):
            return
        # Only if author is registered veteran
        vdata = self.veterans.get(message.author.id)
        if not vdata:
            return
        now_ts = get_now()
        cooldown = self.config.get("message_cooldown_seconds", 60)
        if now_ts - vdata.last_message_time < cooldown:
            return
        vdata.last_message_time = now_ts
        # Add XP and coins
        vdata.add_xp_and_coins(self.config.get("xp_per_message", 5), self.config.get("coins_per_message", 2))
        self.save_data()
        # Optionally update the member's plant message if in personal channel
        # We won't update automatically to avoid editing frequently; the member can refresh by pressing buttons

    @tasks.loop(minutes=1.0)
    async def degrade_task(self) -> None:
        """Background task that periodically degrades the water level of all plants and handles death."""
        # This loop runs every minute but we apply water decrease only at configured interval
        now_ts = get_now()
        interval_minutes = self.config.get("water_decrease_interval_minutes", 60)
        # Use a static attribute to remember last run
        if not hasattr(self.degrade_task, "last_degrade"):
            setattr(self.degrade_task, "last_degrade", now_ts)
        last_degrade = getattr(self.degrade_task, "last_degrade")
        if now_ts - last_degrade < (interval_minutes * 60):
            return
        setattr(self.degrade_task, "last_degrade", now_ts)
        # Iterate veterans and degrade water
        for user_id, vdata in list(self.veterans.items()):
            vdata.degrade()
            if not vdata.is_alive():
                # Plant died – remove veteran role and delete channel
                guilds: List[discord.Guild] = self.guilds
                for guild in guilds:
                    member = guild.get_member(user_id)
                    if member:
                        role_id = self.config.get("veteran_role_id")
                        if role_id:
                            role = guild.get_role(role_id)
                            if role:
                                try:
                                    await member.remove_roles(role, reason="Plant died")
                                except discord.Forbidden:
                                    pass
                    # Remove channel
                    if vdata.channel_id:
                        channel = guild.get_channel(vdata.channel_id)
                        if channel:
                            try:
                                await channel.delete(reason="Plant died")
                            except discord.Forbidden:
                                pass
                # Remove data entry
                del self.veterans[user_id]
        # Save after modifications
        self.save_data()

    def save_data(self) -> None:
        """Persist all veteran data to disk."""
        to_save = {str(uid): v.to_dict() for uid, v in self.veterans.items()}
        save_json(DATA_FILE, to_save)


def main() -> None:
    """Entry point to run the bot."""
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        # Attempt to load from .env file (simple KEY=VALUE per line)
        env_path = os.path.join(os.path.dirname(__file__), ".env")
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    if line.strip() and not line.startswith("#"):
                        key, eq, value = line.strip().partition("=")
                        if key == "DISCORD_TOKEN":
                            token = value
                            break
    if not token:
        raise RuntimeError("Bot token not found. Set DISCORD_TOKEN environment variable or add it to .env")
    bot = VeteranBot(command_prefix="!")
    bot.run(token)


if __name__ == "__main__":
    main()