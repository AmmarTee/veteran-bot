import Fastify from 'fastify'

const PORT = process.env.PORT || 8080
const PANEL_ORIGIN = process.env.PANEL_BASE_URL || process.env.CORS_ORIGIN

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

// --- In-memory Listings API (demo) ---
const listings = []
let nextId = 1

app.get('/listings', async () => ({ items: listings }))
app.post('/listings', async (req, reply) => {
  try {
    const body = await req.body
    const item = {
      id: nextId++,
      title: body?.title || 'Untitled',
      price: Number(body?.price ?? 0),
      created_at: new Date().toISOString(),
    }
    listings.push(item)
    reply.code(201)
    return item
  } catch (e) {
    reply.code(400)
    return { error: 'Invalid payload' }
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
