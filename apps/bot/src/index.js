import { Client, GatewayIntentBits, Partials, Events, REST, Routes, SlashCommandBuilder, EmbedBuilder, ActionRowBuilder, ButtonBuilder, ButtonStyle, PermissionsBitField, ChannelType } from 'discord.js'

const token = process.env.DISCORD_TOKEN
const guildId = process.env.GUILD_ID
const mainChannelId = process.env.MAIN_CHANNEL_ID // optional
const clientId = process.env.DISCORD_CLIENT_ID
const apiBase = process.env.API_BASE_URL || 'http://localhost:8080'

if (!token) {
  console.error('DISCORD_TOKEN is required')
  process.exit(1)
}

const client = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildMembers,
    GatewayIntentBits.GuildMessages,
    GatewayIntentBits.MessageContent,
  ],
  partials: [Partials.Channel],
})

client.once(Events.ClientReady, async () => {
  console.log(`Bot logged in as ${client.user.tag}`)
  // Register commands (guild-scoped for fast updates)
  if (clientId && guildId) {
    try {
      const commands = [
        new SlashCommandBuilder().setName('ping').setDescription('Check bot latency'),
        new SlashCommandBuilder().setName('card').setDescription('Show your wallet card'),
        new SlashCommandBuilder().setName('claim').setDescription('Claim your daily coins'),
        new SlashCommandBuilder().setName('setup_economy').setDescription('Create Coin Economy category & channels'),
        new SlashCommandBuilder().setName('seed_market').setDescription('Seed marketplace with starter listings'),
        new SlashCommandBuilder().setName('leaderboard_refresh').setDescription('Refresh the leaderboard message'),
      ].map(c => c.toJSON())
      const rest = new REST({ version: '10' }).setToken(token)
      await rest.put(Routes.applicationGuildCommands(clientId, guildId), { body: commands })
      console.log('Registered slash commands')
    } catch (e) {
      console.log('Failed to register commands:', e?.message || e)
    }
  } else {
    console.log('DISCORD_CLIENT_ID or GUILD_ID not set; skipping command registration')
  }
  try {
    let channel = null
    if (mainChannelId) {
      channel = await client.channels.fetch(mainChannelId).catch(() => null)
    } else if (guildId) {
      const guild = await client.guilds.fetch(guildId).catch(() => null)
      if (guild) {
        const chans = await guild.channels.fetch()
        channel = chans?.find((c) => c?.isTextBased?.() && c?.name?.toLowerCase()?.includes('main')) || null
      }
    }
    if (channel && channel.isTextBased()) {
      await channel.send('✅ Bot is online and ready!')
    } else {
      console.log('No channel found to announce status. Set MAIN_CHANNEL_ID to enable status messages.')
    }
  } catch (e) {
    console.log('Unable to post online status:', e?.message || e)
  }
})

async function getConfig() {
  if (!guildId) return null
  try {
    const res = await fetch(`${apiBase}/config/${guildId}`)
    if (res.ok) return await res.json()
    return null
  } catch { return null }
}

async function saveConfig(partial) {
  if (!guildId) return null
  try {
    const res = await fetch(`${apiBase}/config/${guildId}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(partial)
    })
    if (!res.ok) return null
    return await res.json()
  } catch {
    return null
  }
}

async function ensureEconomyChannels(interaction) {
  const guild = interaction.guild
  const me = interaction.guild.members.me
  // Create/find category
  const catName = '💰 Coin Economy'
  let category = guild.channels.cache.find(c => c.type === ChannelType.GuildCategory && c.name === catName)
  if (!category) {
    category = await guild.channels.create({ name: catName, type: ChannelType.GuildCategory })
  }
  const everyone = guild.roles.everyone
  const baseOverwrites = [
    { id: everyone.id, deny: [PermissionsBitField.Flags.SendMessages], allow: [PermissionsBitField.Flags.ViewChannel, PermissionsBitField.Flags.ReadMessageHistory] },
    { id: me.id, allow: [PermissionsBitField.Flags.ViewChannel, PermissionsBitField.Flags.SendMessages, PermissionsBitField.Flags.EmbedLinks, PermissionsBitField.Flags.ManageMessages] }
  ]
  async function createOrFind(name, extraOverwrites = []) {
    let ch = category.children?.cache?.find?.(c => c.name === name) || guild.channels.cache.find(c => c.parentId === category.id && c.name === name)
    if (!ch) ch = await guild.channels.create({ name, type: ChannelType.GuildText, parent: category.id, permissionOverwrites: [...baseOverwrites, ...extraOverwrites] })
    return ch
  }
  const hub = await createOrFind('coin-hub')
  const shop = await createOrFind('shop')
  const leaderboard = await createOrFind('leaderboard')
  const quests = await createOrFind('quests')
  const announcements = await createOrFind('coin-announcements', [
    // Admins can customize perms later
  ])
  const transactions = await createOrFind('coin-transactions', [
    { id: everyone.id, deny: [PermissionsBitField.Flags.ViewChannel, PermissionsBitField.Flags.SendMessages] },
  ])
  await saveConfig({
    guildId,
    categoryId: category.id,
    hubChannelId: hub.id,
    shopChannelId: shop.id,
    leaderboardChannelId: leaderboard.id,
    questsChannelId: quests.id,
    announcementsChannelId: announcements.id,
    transactionsChannelId: transactions.id,
  })
  // Post Hub if not present
  const pinned = (await hub.messages.fetchPinned()).first()
  if (!pinned) {
    const msg = await hub.send(buildHubMessage())
    await msg.pin().catch(()=>{})
  }
  return { category, hub, shop, leaderboard, quests, announcements, transactions }
}

function buildHubMessage() {
  const embed = new EmbedBuilder().setTitle('Coin Hub').setDescription('Welcome to the Legocraft economy! Use the buttons below.').setColor(0x0ea5e9)
  const row = new ActionRowBuilder().addComponents(
    new ButtonBuilder().setCustomId('hub:card').setStyle(ButtonStyle.Primary).setLabel('My Card'),
    new ButtonBuilder().setCustomId('hub:shop').setStyle(ButtonStyle.Secondary).setLabel('Shop'),
    new ButtonBuilder().setCustomId('hub:quests').setStyle(ButtonStyle.Secondary).setLabel('Quests'),
    new ButtonBuilder().setCustomId('hub:claim').setStyle(ButtonStyle.Success).setLabel('Claim Daily'),
    new ButtonBuilder().setCustomId('hub:help').setStyle(ButtonStyle.Secondary).setLabel('Help'),
  )
  return { embeds: [embed], components: [row] }
}

async function postTxEmbed(type, fields = []) {
  const cfg = await getConfig()
  if (!cfg?.transactionsChannelId) return
  const ch = await client.channels.fetch(cfg.transactionsChannelId).catch(() => null)
  if (!ch || !ch.isTextBased()) return
  const embed = new EmbedBuilder().setTitle(`TX: ${type}`).setColor(type === 'earn' ? 0x22c55e : 0xef4444).addFields(fields)
  ch.send({ embeds: [embed] }).catch(()=>{})
}
client.on(Events.InteractionCreate, async (interaction) => {
  if (!interaction.isChatInputCommand()) return
  try {
  if (interaction.commandName === 'ping') {
    const t = Date.now()
    await interaction.reply({ content: 'Pong!', ephemeral: true })
    const dt = Date.now() - t
    return interaction.followUp({ content: `Latency: ${dt}ms`, ephemeral: true })
  }
  if (interaction.commandName === 'card') {
    await interaction.deferReply({ ephemeral: true })
    const res = await fetch(`${apiBase}/wallet/${interaction.user.id}`).then(r => r.json()).catch(() => null)
    if (!res || res.error) return interaction.editReply('Could not fetch wallet')
    const embed = new EmbedBuilder()
      .setTitle('Your Card')
      .addFields(
        { name: 'Balance', value: String(res.wallet_balance), inline: true },
        { name: 'Escrow', value: String(res.escrow_balance), inline: true },
      )
      .setFooter({ text: 'Legocraft Economy' })
    return interaction.editReply({ embeds: [embed] })
  }
  if (interaction.commandName === 'claim') {
    await interaction.deferReply({ ephemeral: true })
    const res = await fetch(`${apiBase}/wallet/claim`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ discord_id: interaction.user.id, username: interaction.user.username })
    }).then(r => r.json()).catch(() => null)
    if (!res) return interaction.editReply('Error contacting API')
    if (res.error === 'cooldown') return interaction.editReply(`Already claimed. Next at ${res.next_at}`)
    if (res.ok) return interaction.editReply(`You received ${res.amount} coins!`)
    return interaction.editReply('Could not claim now')
  }
  if (interaction.commandName === 'setup_economy') {
    await interaction.deferReply({ ephemeral: true })
    const res = await ensureEconomyChannels(interaction)
    await interaction.editReply('✅ Economy channels ready. Hub pinned in #coin-hub.')
    return
  }
  if (interaction.commandName === 'seed_market') {
    await interaction.deferReply({ ephemeral: true })
    const seeds = [
      { title: '$10,000 In-Game Money', price: 100 },
      { title: 'VIP (7 days)', price: 800 },
      { title: 'MVP (30 days)', price: 3000 },
      { title: 'Duck Hat Cosmetic', price: 500 },
      { title: 'Mystery Box (Basic)', price: 250 },
    ]
    let ok = 0
    for (const s of seeds) {
      try { await fetch(`${apiBase}/listings`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: s.title, price: s.price }) }) ; ok++ } catch {}
    }
    await interaction.editReply(`Seeded ${ok}/${seeds.length} listings.`)
    await postTxEmbed('list', [ { name: 'Seed', value: `${ok} listings created` }])
    return
  }
  if (interaction.commandName === 'leaderboard_refresh') {
    await interaction.deferReply({ ephemeral: true })
    const cfg = await getConfig()
    if (!cfg?.leaderboardChannelId) return interaction.editReply('No leaderboard channel configured. Run /setup_economy first.')
    const res = await fetch(`${apiBase}/users`).then(r => r.json()).catch(()=>null)
    if (!res) return interaction.editReply('Failed to fetch users')
    const top = (res.items || []).sort((a,b)=>b.wallet_balance - a.wallet_balance).slice(0,10)
    const lines = top.map((u,i)=>`#${i+1} <@${u.discord_id}> — ${u.wallet_balance}`).join('\n') || 'No data.'
    const ch = await client.channels.fetch(cfg.leaderboardChannelId).catch(()=>null)
    if (ch?.isTextBased()) await ch.send({ embeds: [ new EmbedBuilder().setTitle('Top 10 Balances').setDescription(lines).setColor(0xf59e0b) ] })
    await interaction.editReply('Leaderboard refreshed.')
    return
  }
  } catch (e) {
    try { await interaction.reply({ ephemeral: true, content: 'Something went wrong processing your command.' }) } catch {}
  }
})

client.on(Events.InteractionCreate, async (interaction) => {
  if (!interaction.isButton()) return
  try {
    if (interaction.customId === 'hub:help') {
      return interaction.reply({ ephemeral: true, content: 'Earn coins via daily claim, quests, and trades. Use Shop to buy/sell. All purchases are private.' })
    }
    if (interaction.customId === 'hub:card') {
      const res = await fetch(`${apiBase}/wallet/${interaction.user.id}`).then(r=>r.json()).catch(()=>null)
      if (!res || res.error) return interaction.reply({ ephemeral: true, content: 'Could not load wallet.' })
      const embed = new EmbedBuilder().setTitle('Your Card').addFields(
        { name: 'Balance', value: String(res.wallet_balance), inline: true },
        { name: 'Escrow', value: String(res.escrow_balance), inline: true },
      ).setColor(0x0ea5e9)
      return interaction.reply({ ephemeral: true, embeds: [embed] })
    }
    if (interaction.customId === 'hub:claim') {
      const res = await fetch(`${apiBase}/wallet/claim`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ discord_id: interaction.user.id, username: interaction.user.username }) }).then(r => r.json()).catch(()=>null)
      if (!res) return interaction.reply({ ephemeral: true, content: 'Error contacting API.' })
      if (res.error === 'cooldown') return interaction.reply({ ephemeral: true, content: `Already claimed. Next at ${res.next_at}` })
      if (res.ok) {
        await postTxEmbed('earn', [ { name: 'User', value: `<@${interaction.user.id}>` }, { name: 'Reason', value: 'daily_claim' }, { name: 'Amount', value: String(res.amount) } ])
        return interaction.reply({ ephemeral: true, content: `You received ${res.amount} coins!` })
      }
      return interaction.reply({ ephemeral: true, content: 'Could not claim now.' })
    }
    if (interaction.customId === 'hub:shop') {
      const data = await fetch(`${apiBase}/listings`).then(r=>r.json()).catch(()=>null)
      if (!data) return interaction.reply({ ephemeral: true, content: 'Failed to load listings.' })
      const items = (data.items || []).slice(0, 10)
      if (items.length === 0) return interaction.reply({ ephemeral: true, content: 'No listings yet. Use Seed or Sell Item.' })
      const rows = []
      for (const item of items) {
        const row = new ActionRowBuilder().addComponents(
          new ButtonBuilder().setCustomId(`shop:buy:${item.id}`).setStyle(ButtonStyle.Success).setLabel(`Buy 1 — ${item.price}`),
        )
        rows.push(row)
      }
      const embed = new EmbedBuilder().setTitle('Marketplace').setDescription('Click to buy 1 unit.').setColor(0x22c55e)
      return interaction.reply({ ephemeral: true, embeds: [embed], components: rows })
    }
    if (interaction.customId.startsWith('shop:buy:')) {
      const listingId = interaction.customId.split(':')[2]
      const res = await fetch(`${apiBase}/orders`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ listing_id: Number(listingId), qty: 1, buyer_discord_id: interaction.user.id, username: interaction.user.username }) }).then(r=>r.json()).catch(()=>null)
      if (!res) return interaction.reply({ ephemeral: true, content: 'Error contacting API.' })
      if (res.error) return interaction.reply({ ephemeral: true, content: `Purchase failed: ${res.error}` })
      await postTxEmbed('buy', [ { name: 'Buyer', value: `<@${interaction.user.id}>` }, { name: 'Order', value: String(res.order_id) }, { name: 'Total', value: String(res.total) } ])
      return interaction.reply({ ephemeral: true, content: `Purchased! Order #${res.order_id} — Total ${res.total}` })
    }
  } catch (e) {
    return interaction.reply({ ephemeral: true, content: 'Something went wrong.' }).catch(()=>{})
  }
})

client.login(token)
