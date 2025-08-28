export type AppRole = 'SUPERADMIN' | 'ADMIN' | 'OPERATOR' | 'SUPPORT' | 'AUDITOR'

function parseCsv(ids?: string) { return (ids || '').split(',').map(s => s.trim()).filter(Boolean) }

export function mapDiscordRolesToAppRole(discordRoleIds: string[]): AppRole | null {
  const sup = parseCsv(process.env.DISCORD_SUPERADMIN_ROLE_IDS)
  const adm = parseCsv(process.env.DISCORD_ADMIN_ROLE_IDS)
  const op = parseCsv(process.env.DISCORD_OPERATOR_ROLE_IDS)
  const suppt = parseCsv(process.env.DISCORD_SUPPORT_ROLE_IDS)
  const aud = parseCsv(process.env.DISCORD_AUDITOR_ROLE_IDS)

  if (discordRoleIds.some(id => sup.includes(id))) return 'SUPERADMIN'
  if (discordRoleIds.some(id => adm.includes(id))) return 'ADMIN'
  if (discordRoleIds.some(id => op.includes(id))) return 'OPERATOR'
  if (discordRoleIds.some(id => suppt.includes(id))) return 'SUPPORT'
  if (discordRoleIds.some(id => aud.includes(id))) return 'AUDITOR'
  return null
}

