import { v4 as uuidv4 } from 'uuid';
import { ActionRowBuilder, ButtonBuilder, ButtonStyle, EmbedBuilder, ModalBuilder, TextInputBuilder, TextInputStyle } from 'discord.js';
import { createListing, getActiveListings, updateBalances, getUser, logTx } from './db.js';
import { sendAdminLog } from './adminFeed.js';

export function sellModal() {
  const m = new ModalBuilder().setCustomId('shop:sellmodal').setTitle('Create Listing');
  m.addComponents(
    new ActionRowBuilder().addComponents(new TextInputBuilder().setCustomId('sku').setLabel('SKU / Item').setStyle(TextInputStyle.Short).setRequired(true)),
    new ActionRowBuilder().addComponents(new TextInputBuilder().setCustomId('qty').setLabel('Quantity').setStyle(TextInputStyle.Short).setRequired(true)),
    new ActionRowBuilder().addComponents(new TextInputBuilder().setCustomId('price').setLabel('Unit Price').setStyle(TextInputStyle.Short).setRequired(true))
  );
  return m;
}

export async function handleSellSubmit(db, client, cfg, interaction) {
  const sku = interaction.fields.getTextInputValue('sku');
  const qty = Math.max(1, parseInt(interaction.fields.getTextInputValue('qty')||'1', 10));
  const unit = Math.max(1, parseInt(interaction.fields.getTextInputValue('price')||'1', 10));
  const listing = {
    listing_id: uuidv4(),
    guild_id: interaction.guildId,
    seller_id: interaction.user.id,
    sku,
    qty,
    unit_price: unit,
    fee_rate: cfg?.fee_rate ?? 0.08,
    expires_at: null,
    status: 'active',
    message_channel_id: cfg?.shop_channel_id || interaction.channelId,
    message_id: null,
  };
  const embed = new EmbedBuilder()
    .setTitle(`Listing: ${sku}`)
    .setDescription(`Seller: <@${listing.seller_id}>\nQty: ${qty}\nPrice: ${unit} coins each`)
    .setColor(0x9B59B6);
  const row = new ActionRowBuilder().addComponents(
    new ButtonBuilder().setCustomId(`shop:buy:${listing.listing_id}`).setLabel('Buy').setStyle(ButtonStyle.Success),
    new ButtonBuilder().setCustomId(`shop:cancel:${listing.listing_id}`).setLabel('Cancel').setStyle(ButtonStyle.Secondary)
  );
  const shopCh = await client.channels.fetch(listing.message_channel_id).catch(() => null);
  if (!shopCh || !shopCh.isTextBased()) {
    await interaction.reply({ content: 'Shop channel is not configured.', ephemeral: true });
    return;
  }
  const msg = await shopCh.send({ embeds: [embed], components: [row] });
  listing.message_id = msg.id;
  await createListing(db, listing);
  await interaction.reply({ content: 'Listing created.', ephemeral: true });
}

export async function handleBuy(db, client, cfg, interaction, listing) {
  const buyer = await getUser(db, interaction.user.id);
  const total = listing.unit_price * listing.qty;
  if (buyer.wallet_balance < total) {
    await interaction.reply({ content: `Insufficient funds. Need ${total} coins.`, ephemeral: true });
    return;
  }
  await updateBalances(db, interaction.user.id, -total, total);
  await logTx(db, { tx_id: uuidv4(), guild_id: interaction.guildId, type: 'buy', actor_id: interaction.user.id, amount: total, reason: 'Buy listing', meta: { listing_id: listing.listing_id } });
  await sendAdminLog(client, cfg, new EmbedBuilder().setTitle('Buy').setDescription(`<@${interaction.user.id}> escrowed ${total} coins for listing ${listing.listing_id}`).setColor(0x3498DB));
  await interaction.reply({ content: `Escrowed ${total} coins. An admin/seller will fulfil your order.`, ephemeral: true });
}

