import { Client, GatewayIntentBits, Partials, Events } from 'discord.js'

const token = process.env.DISCORD_TOKEN
const guildId = process.env.GUILD_ID
const mainChannelId = process.env.MAIN_CHANNEL_ID // optional

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

client.login(token)

