"use client"
import { useEffect, useState } from 'react'

type TxEvent = { tx_id: string; type: string; actor_id: string; amount: number; created_at: string; meta?: any }

export default function LiveFeed() {
  const [events, setEvents] = useState<TxEvent[]>([])
  const api = process.env.NEXT_PUBLIC_API_BASE_URL || process.env.NEXT_PUBLIC_API_URL

  useEffect(() => {
    if (!api) return
    const es = new EventSource(`${api}/streams/tx`)
    es.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data)
        setEvents((prev) => [data, ...prev].slice(0, 50))
      } catch {}
    }
    es.onerror = () => {
      es.close()
      // will reconnect on rerender when component remounts or page navigates
    }
    return () => es.close()
  }, [api])

  return (
    <div className="space-y-2">
      <h2 className="text-lg font-semibold">Live Transactions</h2>
      <div className="border rounded bg-white divide-y">
        {events.length === 0 && <div className="p-3 text-gray-500">Waiting for events…</div>}
        {events.map((e) => (
          <div key={e.tx_id} className="p-3 text-sm flex items-center justify-between">
            <div>
              <span className="font-medium mr-2">{e.type}</span>
              <span className="text-gray-600">{e.actor_id}</span>
            </div>
            <div className="tabular-nums">{e.amount}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

