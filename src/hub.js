import { ActionRowBuilder, ButtonBuilder, ButtonStyle, EmbedBuilder } from 'discord.js';
import { getUser } from './db.js';

export function hubEmbed() {
  return new EmbedBuilder()
    .setTitle('🪙 Coin Hub')
    .setDescription('Use the buttons below to manage your wallet, view the shop, and claim dailies.')
    .setColor(0xF1C40F);
}

export function hubButtons() {
  return new ActionRowBuilder().addComponents(
    new ButtonBuilder().setCustomId('hub:card').setLabel('My Card').setStyle(ButtonStyle.Primary),
    new ButtonBuilder().setCustomId('hub:shop').setLabel('Shop').setStyle(ButtonStyle.Secondary),
    new ButtonBuilder().setCustomId('hub:daily').setLabel('Claim Daily').setStyle(ButtonStyle.Success),
    new ButtonBuilder().setCustomId('hub:help').setLabel('Help').setStyle(ButtonStyle.Secondary)
  );
}

export async function showCard(db, interaction) {
  const u = await getUser(db, interaction.user.id);
  const e = new EmbedBuilder()
    .setTitle(`${interaction.user.username}'s Card`)
    .addFields(
      { name: 'Balance', value: `${u.wallet_balance} coins`, inline: true },
      { name: 'Escrow', value: `${u.escrow_balance} coins`, inline: true },
      { name: 'Streak', value: `${u.streak_days} days`, inline: true },
    )
    .setColor(0x2ECC71)
    .setFooter({ text: 'Your data is private to you.' });
  await interaction.reply({ embeds: [e], ephemeral: true });
}

