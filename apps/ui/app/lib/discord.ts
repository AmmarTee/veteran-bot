const DISCORD_API = 'https://discord.com/api'

export async function fetchGuildMember(opts: { userId: string, guildId: string, botToken: string }) {
  const res = await fetch(`${DISCORD_API}/guilds/${opts.guildId}/members/${opts.userId}`, {
    headers: { Authorization: `Bot ${opts.botToken}` },
  })
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`Discord API error ${res.status}`)
  return await res.json() as { user: { id: string }, roles: string[] }
}

