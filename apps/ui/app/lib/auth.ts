import NextAuth, { AuthOptions } from 'next-auth'
import DiscordProvider from 'next-auth/providers/discord'
import { fetchGuildMember } from './discord'
import { mapDiscordRolesToAppRole } from './rbac'

export const authOptions: AuthOptions = {
  providers: [
    DiscordProvider({
      clientId: process.env.DISCORD_CLIENT_ID!,
      clientSecret: process.env.DISCORD_CLIENT_SECRET!,
      authorization: { params: { scope: 'identify guilds' } },
    })
  ],
  callbacks: {
    async signIn({ user }) {
      try {
        const guildId = process.env.GUILD_ID!
        const botToken = process.env.DISCORD_TOKEN!
        if (!guildId || !botToken) return false
        const member = await fetchGuildMember({ userId: user.id as string, guildId, botToken })
        return !!member
      } catch {
        return false
      }
    },
    async session({ session, token }) {
      const guildId = process.env.GUILD_ID
      const botToken = process.env.DISCORD_TOKEN
      if (guildId && botToken && token?.sub) {
        try {
          const member = await fetchGuildMember({ userId: token.sub!, guildId, botToken })
          const appRole = mapDiscordRolesToAppRole(member?.roles ?? [])
          ;(session as any).appRole = appRole
          ;(session as any).roles = member?.roles ?? []
        } catch {}
      }
      return session
    },
  },
  session: { strategy: 'jwt' },
  secret: process.env.NEXTAUTH_SECRET,
}

export const { handlers, auth, signIn, signOut } = NextAuth(authOptions)

