import 'dotenv/config';
import { REST, Routes } from 'discord.js';
import { registerSlashData } from './commands.js';

async function main() {
  const token = process.env.DISCORD_TOKEN;
  const appId = process.env.APPLICATION_ID;
  const guildId = process.env.TEST_GUILD_ID; // optional for dev
  const rest = new REST({ version: '10' }).setToken(token);
  const body = registerSlashData();
  if (guildId) {
    await rest.put(Routes.applicationGuildCommands(appId, guildId), { body });
    console.log('Registered guild commands');
  } else {
    await rest.put(Routes.applicationCommands(appId), { body });
    console.log('Registered global commands');
  }
}

main().catch((e) => { console.error(e); process.exit(1); });

