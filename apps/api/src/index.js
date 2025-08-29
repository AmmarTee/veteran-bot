import Fastify from 'fastify'
import { prisma } from './db.js'

const PORT = process.env.PORT || 8080
const PANEL_ORIGIN = process.env.PANEL_BASE_URL || process.env.CORS_ORIGIN
const DAILY_CLAIM = Number(process.env.DAILY_CLAIM || 100)
const MARKET_FEE_PCT = Number(process.env.MARKET_FEE || 0.08)

const app = Fastify({ logger: true })

// Basic CORS for panel origin
app.addHook('onRequest', async (req, res) => {
  if (!PANEL_ORIGIN) return
  res.header('Access-Control-Allow-Origin', PANEL_ORIGIN)
  res.header('Vary', 'Origin')
  res.header('Access-Control-Allow-Credentials', 'true')
  res.header('Access-Control-Allow-Headers', req.headers['access-control-request-headers'] || 'content-type,authorization,idempotency-key')
})

app.options('/*', async (_, reply) => {
  reply.code(204)
  return ''
})

app.get('/healthz', async () => ({ ok: true }))

// --- DB helpers ---
async function ensureUser(discordId, username) {
  const user = await prisma.user.upsert({
    where: { discordId },
    create: { discordId, username, wallet: { create: {} } },
    update: { username },
    include: { wallet: true },
  })
  if (!user.wallet) {
    await prisma.wallet.create({ data: { userId: user.id } })
  }
  return prisma.user.findUnique({ where: { discordId }, include: { wallet: true } })
}

// --- Users ---
app.get('/users', async (req) => {
  const limit = Math.min(Number(req.query?.limit ?? 50), 200)
  const users = await prisma.user.findMany({
    take: limit,
    orderBy: { id: 'asc' },
    include: { wallet: true },
  })
  return { items: users.map(u => ({
    id: u.id,
    discord_id: u.discordId,
    username: u.username,
    wallet_balance: Number(u.wallet?.walletBalance ?? 0n),
    escrow_balance: Number(u.wallet?.escrowBalance ?? 0n),
    frozen: u.frozen,
    created_at: u.createdAt,
  })) }
})

// --- Wallet endpoints ---
app.get('/wallet/:discordId', async (req, reply) => {
  const { discordId } = req.params
  const user = await prisma.user.findUnique({ where: { discordId }, include: { wallet: true } })
  if (!user) { reply.code(404); return { error: 'not_found' } }
  return {
    discord_id: user.discordId,
    wallet_balance: Number(user.wallet?.walletBalance ?? 0n),
    escrow_balance: Number(user.wallet?.escrowBalance ?? 0n),
    last_daily_claim_at: user.lastDailyClaimAt ?? null,
  }
})

app.post('/wallet/earn', async (req, reply) => {
  const idem = req.headers['idempotency-key'] || req.headers['x-idempotency-key']
  const { discord_id, amount, reason, username } = req.body || {}
  if (!discord_id || typeof amount !== 'number') { reply.code(400); return { error: 'bad_request' } }
  try {
    const res = await prisma.$transaction(async (tx) => {
      if (idem) {
        const exists = await tx.transaction.findFirst({ where: { idemKey: String(idem) } })
        if (exists) return { reused: true, tx: exists }
      }
      const user = await ensureUser(discord_id, username)
      const before = user.wallet?.walletBalance ?? 0n
      const after = before + BigInt(amount)
      await tx.wallet.update({ where: { userId: user.id }, data: { walletBalance: after } })
      const t = await tx.transaction.create({ data: {
        type: 'earn', userId: user.id, amount: BigInt(amount), fee: 0n,
        beforeBalance: before, afterBalance: after, meta: { reason }, idemKey: idem ? String(idem) : null,
      }})
      return { reused: false, tx: t }
    })
    reply.code(res.reused ? 200 : 201)
    return { ok: true, tx_id: res.tx.id }
  } catch (e) {
    reply.code(500)
    return { error: 'server_error' }
  }
})

app.post('/wallet/claim', async (req, reply) => {
  const { discord_id, username } = req.body || {}
  if (!discord_id) { reply.code(400); return { error: 'bad_request' } }
  const user = await ensureUser(discord_id, username)
  const now = new Date()
  if (user.lastDailyClaimAt) {
    const delta = now.getTime() - new Date(user.lastDailyClaimAt).getTime()
    if (delta < 24*60*60*1000) { reply.code(429); return { error: 'cooldown', next_at: new Date(new Date(user.lastDailyClaimAt).getTime() + 24*60*60*1000).toISOString() } }
  }
  try {
    await prisma.$transaction(async (tx) => {
      const u = await tx.user.update({ where: { id: user.id }, data: { lastDailyClaimAt: now } })
      const wallet = await tx.wallet.findUnique({ where: { userId: u.id } })
      const before = wallet?.walletBalance ?? 0n
      const after = before + BigInt(DAILY_CLAIM)
      await tx.wallet.update({ where: { userId: u.id }, data: { walletBalance: after } })
      await tx.transaction.create({ data: {
        type: 'earn', userId: u.id, amount: BigInt(DAILY_CLAIM), fee: 0n,
        beforeBalance: before, afterBalance: after, meta: { reason: 'daily_claim' }, idemKey: null,
      }})
    })
    return { ok: true, amount: DAILY_CLAIM }
  } catch (e) {
    reply.code(500); return { error: 'server_error' }
  }
})

// --- Listings API (DB) ---
app.get('/listings', async () => {
  const rows = await prisma.listing.findMany({ orderBy: { createdAt: 'desc' }, take: 100 })
  return { items: rows.map(r => ({ id: r.id, title: r.title, price: Number(r.price), created_at: r.createdAt })) }
})
app.post('/listings', async (req, reply) => {
  const body = req.body || {}
  const title = String(body.title || 'Untitled')
  const price = Number(body.price ?? 0)
  const sellerDiscordId = body.discord_id || null
  let sellerId = null
  if (sellerDiscordId) {
    const seller = await ensureUser(String(sellerDiscordId))
    sellerId = seller.id
  }
  if (!sellerId) {
    const sys = await ensureUser('system', 'System')
    sellerId = sys.id
  }
  const rec = await prisma.listing.create({ data: { title, price: BigInt(price), qty: 1, sellerId } })
  reply.code(201)
  return { id: rec.id, title: rec.title, price: Number(rec.price), created_at: rec.createdAt }
})

// --- Orders (simple immediate fulfil) ---
app.post('/orders', async (req, reply) => {
  const { listing_id, qty = 1, buyer_discord_id, username } = req.body || {}
  if (!listing_id || !buyer_discord_id) { reply.code(400); return { error: 'bad_request' } }
  const quantity = Math.max(1, Number(qty))
  try {
    const res = await prisma.$transaction(async (tx) => {
      const listing = await tx.listing.findUnique({ where: { id: Number(listing_id) } })
      if (!listing || listing.status !== 'active') throw new Error('listing_unavailable')
      if (listing.qty < quantity) throw new Error('insufficient_qty')

      const buyer = await ensureUser(String(buyer_discord_id), username)
      const seller = await tx.user.findUnique({ where: { id: listing.sellerId }, include: { wallet: true } })
      if (!seller) throw new Error('seller_missing')

      const unit = listing.price
      const total = unit * BigInt(quantity)
      const feePct = Math.round(MARKET_FEE_PCT * 100) // percent * 100
      const fee = (total * BigInt(feePct)) / 100n
      const sellerProceeds = total - fee

      const buyerWallet = await tx.wallet.findUnique({ where: { userId: buyer.id } })
      const buyerBefore = buyerWallet?.walletBalance ?? 0n
      if (buyerBefore < total) throw new Error('insufficient_funds')
      const buyerAfter = buyerBefore - total
      await tx.wallet.update({ where: { userId: buyer.id }, data: { walletBalance: buyerAfter } })
      await tx.transaction.create({ data: {
        type: 'spend', userId: buyer.id, amount: total, fee: 0n,
        beforeBalance: buyerBefore, afterBalance: buyerAfter, meta: { reason: 'buy', listing_id, qty: quantity }, idemKey: null,
      }})

      const sellerWallet = await tx.wallet.findUnique({ where: { userId: seller.id } })
      const sellerBefore = sellerWallet?.walletBalance ?? 0n
      const sellerAfter = sellerBefore + sellerProceeds
      await tx.wallet.update({ where: { userId: seller.id }, data: { walletBalance: sellerAfter } })
      await tx.transaction.create({ data: {
        type: 'earn', userId: seller.id, amount: sellerProceeds, fee: fee,
        beforeBalance: sellerBefore, afterBalance: sellerAfter, meta: { reason: 'sell', listing_id, qty: quantity }, idemKey: null,
      }})

      const newQty = listing.qty - quantity
      await tx.listing.update({ where: { id: listing.id }, data: { qty: newQty, status: newQty <= 0 ? 'sold' : 'active' } })

      const order = await tx.order.create({ data: {
        listingId: listing.id,
        buyerId: buyer.id,
        qty: quantity,
        unitPrice: unit,
        fee,
        total,
        status: 'fulfilled',
      }})
      return { order, total, fee, proceeds: sellerProceeds }
    })
    reply.code(201)
    return { ok: true, order_id: res.order.id, total: Number(res.total), fee: Number(res.fee) }
  } catch (e) {
    const msg = (e && e.message) || 'server_error'
    const map = { listing_unavailable: 409, insufficient_qty: 409, insufficient_funds: 402 }
    reply.code(map[msg] || 500)
    return { error: msg }
  }
})

// --- Guild Config ---
app.get('/config/:guildId', async (req, reply) => {
  const { guildId } = req.params
  const cfg = await prisma.guildConfig.findUnique({ where: { guildId } })
  if (!cfg) { reply.code(404); return { error: 'not_found' } }
  return cfg
})

app.put('/config/:guildId', async (req) => {
  const { guildId } = req.params
  const data = req.body || {}
  const cfg = await prisma.guildConfig.upsert({
    where: { guildId },
    create: { guildId, ...data },
    update: { ...data },
  })
  return cfg
})

app.post('/admin/message', async (req, reply) => {
  const { channel_id, content } = req.body || {}
  const token = process.env.DISCORD_TOKEN
  if (!token) {
    reply.code(500)
    return { error: 'missing_token' }
  }
  if (!channel_id || !content) {
    reply.code(400)
    return { error: 'bad_request' }
  }
  try {
    const res = await fetch(`https://discord.com/api/v10/channels/${channel_id}/messages`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bot ${token}`,
      },
      body: JSON.stringify({ content })
    })
    if (!res.ok) {
      reply.code(500)
      return { error: 'discord_error' }
    }
    const msg = await res.json()
    return { ok: true, message_id: msg.id }
  } catch (e) {
    reply.code(500)
    return { error: 'server_error' }
  }
})

app.get('/streams/tx', async (req, reply) => {
  reply
    .header('Content-Type', 'text/event-stream')
    .header('Cache-Control', 'no-cache')
    .header('Connection', 'keep-alive')
    .code(200)

  const send = (obj) => reply.raw.write(`data: ${JSON.stringify(obj)}\n\n`)
  const ping = () => reply.raw.write(`:\n\n`) // comment ping

  // Initial hello
  send({ tx_id: 'bootstrap', type: 'hello', actor_id: 'system', amount: 0, created_at: new Date().toISOString() })

  const interval = setInterval(() => ping(), 15000)
  req.raw.on('close', () => clearInterval(interval))
})

app.listen({ host: '0.0.0.0', port: PORT })
  .then(() => app.log.info(`API listening on :${PORT}`))
  .catch((err) => { app.log.error(err); process.exit(1) })
