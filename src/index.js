import 'dotenv/config';
import { Client, GatewayIntentBits, Partials, Events, EmbedBuilder } from 'discord.js';
import { openDb } from './db.js';
import { registerSlashData, handleSlash, getGuildConfig } from './commands.js';
import { hubButtons, hubEmbed, showCard } from './hub.js';
import { sellModal, handleSellSubmit, handleBuy } from './shop.js';
import { getActiveListings } from './db.js';

const token = process.env.DISCORD_TOKEN;
const databaseUrl = process.env.DATABASE_URL || './data/coins.db';

const db = openDb(databaseUrl);
const client = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildMembers,
    GatewayIntentBits.GuildMessages,
    GatewayIntentBits.MessageContent,
  ],
  partials: [Partials.Channel]
});

client.once(Events.ClientReady, async (c) => {
  console.log(`Logged in as ${c.user.tag}`);
  // Best-effort: ensure hub message exists if configured (no-op otherwise)
});

client.on(Events.InteractionCreate, async (interaction) => {
  if (interaction.isChatInputCommand()) {
    return handleSlash(db, client, interaction);
  }

  if (interaction.isButton()) {
    const [ns, action, arg] = interaction.customId.split(':');
    if (ns === 'hub') {
      if (action === 'card') return showCard(db, interaction);
      if (action === 'shop') {
        const cfg = await getGuildConfig(db, interaction.guildId);
        const listings = await getActiveListings(db, interaction.guildId);
        const e = new EmbedBuilder().setTitle('Shop').setColor(0xE67E22).setDescription(listings.length ? listings.map(l => `• ${l.sku} x${l.qty} — ${l.unit_price} coins (id: ${l.listing_id.slice(0,8)})`).join('\n') : 'No listings yet. Use Sell to create one.');
        return interaction.reply({ embeds: [e], ephemeral: true });
      }
      if (action === 'daily') {
        // Placeholder: implement streak & daily later
        return interaction.reply({ content: 'Daily claimed (placeholder).', ephemeral: true });
      }
      if (action === 'help') {
        return interaction.reply({ content: 'Use My Card for your balance. Open Shop to view items. Create listings with Sell (coming soon).', ephemeral: true });
      }
    }
    if (ns === 'shop') {
      if (action === 'sell') {
        return interaction.showModal(sellModal());
      }
      if (action === 'buy' && arg) {
        const cfg = await getGuildConfig(db, interaction.guildId);
        const listings = await getActiveListings(db, interaction.guildId);
        const listing = listings.find(l => l.listing_id === arg);
        if (!listing) return interaction.reply({ content: 'Listing not found.', ephemeral: true });
        return handleBuy(db, client, cfg, interaction, listing);
      }
    }
  }

  if (interaction.isModalSubmit()) {
    const [ns, action] = interaction.customId.split(':');
    if (ns === 'shop' && action === 'sellmodal') {
      const cfg = await getGuildConfig(db, interaction.guildId);
      return handleSellSubmit(db, client, cfg, interaction);
    }
  }
});

client.login(token);

