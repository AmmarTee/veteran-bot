import { Client, GatewayIntentBits, Partials, Events, REST, Routes, SlashCommandBuilder, EmbedBuilder } from 'discord.js'

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

client.on(Events.InteractionCreate, async (interaction) => {
  if (!interaction.isChatInputCommand()) return
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
})

client.login(token)
