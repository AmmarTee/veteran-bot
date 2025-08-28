# Veteran Club Discord Bot

This repository contains a fully‑functional Discord bot that gamifies the
experience of being a **veteran** member on your server.  The bot keeps
veterans active in a dedicated chat, rewards them with coins and XP for
participating, and lets them grow a virtual plant.  When a veteran’s
plant dies (because it hasn’t been watered on time) their veteran role
is automatically removed.

## Features

* **Rewards for chatting:** The bot listens to messages in one or more
  configured channels and awards XP and coins to veteran members.  To
  prevent abuse there is a configurable cooldown between rewards.
* **Private plant channels:** Each veteran has their own private
  channel (created under a configurable category) where they can view
  their plant stats and interact via buttons.  Buttons are a first
  class feature of `discord.py` version 2.0 and newer – the library
  authors recommend upgrading rather than using third‑party
  components【702007078965881†L1006-L1086】.
* **Watering mechanic:** Veterans must spend coins to water their
  plants.  The water meter decreases over time.  If the water level
  reaches zero the plant dies and the veteran role is removed from the
  member.
* **Coin transfers:** Veterans can send coins to other veterans via a
  button and modal dialog.  A per–day sending limit (and affordability
  check) prevents abuse.
* **Leaderboard:** A button (or slash command) allows anyone to see
  the top veterans ranked by plant age and XP.
* **Slash commands for admins:** Guild administrators can register new
  veterans or update configuration parameters (such as which channels
  to watch for rewards, water costs, etc.) using slash commands.

## Deployment niceties

* **Auto command sync on deploy:** On startup the bot now syncs slash
  commands to all joined guilds, so new/changed commands are available
  immediately after you push and restart.
* **Status announcements:** The bot posts a status message in the
  configured Garden channel when it comes online and when it is about
  to go offline for an update.

## Installation

1. **Clone or extract** this repository.  Inside you will find
   `bot.py`, a `config.json` template and this `README.md`.
2. **Install dependencies.**  This bot relies on the official
   `discord.py` package version 2.1 or newer.  Install it with pip:

   ```sh
   python3 -m pip install -U discord.py
   ```

   If you intend to use slash commands and buttons, you must be on
   version 2.0 or later – earlier versions lack support for these
   components and require third‑party modules like `discord‑components`【702007078965881†L1006-L1086】.

3. **Create a bot account.**  Go to the [Discord Developer
   Portal](https://discord.com/developers/applications), create a new
   application, add a bot user and copy the bot token.
4. **Invite the bot.**  Under the OAuth2 tab generate an invite URL
   with the `bot` and `applications.commands` scopes.  The bot will
   need the following permissions at minimum:

   * Read Messages/View Channels
   * Send Messages
   * Manage Channels (to create/delete veteran channels)
   * Manage Roles (to add/remove the veteran role)
   * Use Slash Commands

5. **Configure the bot.**  Copy the `config.json` file (if it does not
   exist it will be created automatically) and edit the following
   fields:

   * `veteran_role_id` – the numeric ID of the role that marks a
     veteran.  The bot will add this role to newly registered
     veterans and remove it when their plant dies.
   * `veteran_category_id` – the ID of the category under which
     private plant channels will be created.  The bot must have
     permission to manage channels in this category.
   * `reward_channel_ids` – a list of channel IDs where chatting
     should award XP and coins.
   * `water_cost` – coins required to water a plant (buy a bucket).
   * `plant_max_water` – maximum water level of a plant.
   * `water_decrease_interval_minutes` and `water_decrease_amount` –
     how often and by how much the water meter decreases.
   * `xp_per_message` and `coins_per_message` – rewards per eligible
     message.
   * `message_cooldown_seconds` – minimum time between rewards from
     the same user.
   * `max_coins_send_per_day` – daily limit on coins a veteran can
     send to others.

   You can also change these settings at runtime using the `/configure`
   slash command (only administrators may execute it).

6. **Provide the bot token.**  Set the environment variable
   `DISCORD_TOKEN` before running the bot or create a `.env` file in
   the same directory as `bot.py` containing a line like:

   ```env
   DISCORD_TOKEN=your_bot_token_here
   ```

7. **Run the bot.**  Execute the script with Python:

   ```sh
   python3 bot.py
   ```

   On first start the bot will create `data.json` and `config.json` in
   the working directory if they do not already exist.

## Usage

### Registering veterans

* **Automatically:** You can hook your own logic to call
  `bot.create_veteran(member)` when appropriate (e.g. when a member
  reaches a certain level or obtains a role).  The bot does not
  automatically register every new member – you must explicitly call
  the registration routine.
* **Manually:** Use the `/register` slash command.  Only members with
  `Manage Guild` or `Administrator` permission may use this command.

When a veteran is registered the bot will:

1. Create a private text channel in the configured category with
   permissions granting only the veteran and moderators access.
2. Send a message in that channel containing an embed showing the
   veteran’s plant level, XP, coin balance, plant age and water level,
   along with three buttons:
   * **Water Plant** – spend coins to refill the water meter.
   * **Send Coins** – open a modal where the veteran can specify a
     recipient and an amount.  The bot enforces a daily sending limit
     and ensures the recipient is also a veteran.
   * **Leaderboard** – display a leaderboard ranked by plant age and
     XP.

### Earning XP and coins

Veterans earn XP and coins by sending messages in the channels listed
in `reward_channel_ids`.  Each eligible message gives a configured
amount of XP (`xp_per_message`) and coins (`coins_per_message`).  To
prevent spam, the bot records the last message time per user and will
only award rewards once per `message_cooldown_seconds` interval.

### Watering plants and plant death

Each plant has a water meter.  Water gradually decreases based on
`water_decrease_interval_minutes` and `water_decrease_amount`.  When
the meter reaches zero the plant dies:

1. The veteran’s private channel is deleted.
2. The veteran role is removed from the member automatically via
   `member.remove_roles`【702007078965881†L1032-L1047】.
3. Their data record is wiped from `data.json`.

The veteran can keep the plant alive by pressing the **Water Plant**
button, which costs `water_cost` coins and refills the meter to
`plant_max_water`.

### Leaderboards and stats

Veterans and other server members can view rankings using the
**Leaderboard** button or the `/leaderboard` slash command.  The
leaderboard lists the top veterans (up to 20) along with their level,
XP, plant age in days and coin balance.  Individual veterans can view
their own stats with the `/mystats` slash command, which sends an
embed identical to the one in their private channel.

## Extending the bot

The bot is written to be easy to modify.  Persistent data is stored
in `data.json`; configuration is stored in `config.json`.  All
interaction logic lives in `bot.py` inside the `VeteranBot` class.
You can hook into events such as `on_member_update` or
`on_member_join` to automatically register new veterans based on your
own criteria.  Because the bot uses `discord.ui` components rather
than reactions, you do not need to manage low‑level component IDs –
the callbacks are defined inline.

## Limitations

* The bot stores its state in local JSON files.  In a production
  environment you may want to replace this with a real database.
* There is no anti‑spam beyond the simple message cooldown.  You may
  wish to implement additional checks (e.g. word count or message
  length) before awarding rewards.
* Plants are currently represented only by numbers (level, age,
  water meter).  You can enhance the bot by adding images that change
  as the plant levels up.

## References

* The official `discord.py` maintainers recommend upgrading to
  version 2.0 or higher to use interactions such as buttons and
  slash commands rather than relying on third‑party libraries
  (`discord‑components`)【702007078965881†L1006-L1086】.  The sample button code in
  their answer shows how to construct a button and send it in a
  message using `discord_components`【702007078965881†L1032-L1047】; this bot uses the
  modern `discord.ui` API provided by `discord.py` 2.x instead.
