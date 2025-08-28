import { SlashCommandBuilder, PermissionFlagsBits } from 'discord.js';
import { setConfig, getConfig } from './db.js';
import { hubButtons, hubEmbed } from './hub.js';

export const setupCoinSystemCommand = new SlashCommandBuilder()
  .setName('setupcoinsystem')
  .setDescription('Initialize coin economy channels and hub (admin)')
  .setDefaultMemberPermissions(PermissionFlagsBits.ManageGuild);

export function registerSlashData() {
  return [setupCoinSystemCommand.toJSON()];
}

export async function handleSlash(db, client, interaction) {
  if (interaction.commandName === 'setupcoinsystem') {
    if (!interaction.memberPermissions?.has(PermissionFlagsBits.ManageGuild)) {
      await interaction.reply({ content: 'No permission.', ephemeral: true });
      return;
    }
    await interaction.deferReply({ ephemeral: true });

    const guild = interaction.guild;
    const hub = await guild.channels.create({ name: 'coin-hub', reason: 'Coin system hub' });
    const lb = await guild.channels.create({ name: 'leaderboard', reason: 'Coin leaderboard' });
    const shop = await guild.channels.create({ name: 'shop', reason: 'Coin shop' });
    const admin = await guild.channels.create({ name: 'coin-transactions', reason: 'Admin transaction feed' });

    await setConfig(db, guild.id, {
      coin_hub_channel_id: hub.id,
      leaderboard_channel_id: lb.id,
      shop_channel_id: shop.id,
      admin_tx_channel_id: admin.id,
    });

    const hubMsg = await hub.send({ embeds: [hubEmbed()], components: [hubButtons()] });
    try { await hubMsg.pin(); } catch {}

    await interaction.followUp({ content: 'Coin system initialized.', ephemeral: true });
    return;
  }
}

export async function getGuildConfig(db, guildId) {
  return await getConfig(db, guildId);
}

