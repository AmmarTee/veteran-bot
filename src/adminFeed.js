export async function sendAdminLog(client, cfg, embed) {
  if (!cfg?.admin_tx_channel_id) return;
  const ch = await client.channels.fetch(cfg.admin_tx_channel_id).catch(() => null);
  if (!ch || !ch.isTextBased()) return;
  try { await ch.send({ embeds: [embed] }); } catch {}
}

