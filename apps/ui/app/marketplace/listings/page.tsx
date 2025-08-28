"use client"
import { useEffect, useState } from 'react'

type Listing = { id: number; title: string; price: number; created_at: string }

export default function ListingsPage() {
  const [items, setItems] = useState<Listing[]>([])
  const [title, setTitle] = useState('')
  const [price, setPrice] = useState<number | ''>('')
  const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL || process.env.NEXT_PUBLIC_API_URL || ''

  const load = async () => {
    try {
      const res = await fetch(`${apiBase}/listings`, { cache: 'no-store' })
      const data = await res.json()
      setItems(data.items || [])
    } catch {}
  }

  useEffect(() => { load() }, [])

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      await fetch(`${apiBase}/listings`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, price: Number(price || 0) })
      })
      setTitle('')
      setPrice('')
      await load()
    } catch {}
  }

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Listings</h1>
      <form onSubmit={submit} className="flex items-end gap-2">
        <label className="flex flex-col text-sm">
          <span className="text-gray-600">Title</span>
          <input className="border rounded px-2 py-1" value={title} onChange={(e)=>setTitle(e.target.value)} required />
        </label>
        <label className="flex flex-col text-sm">
          <span className="text-gray-600">Price</span>
          <input type="number" className="border rounded px-2 py-1" value={price} onChange={(e)=>setPrice(e.target.value === '' ? '' : Number(e.target.value))} min={0} step="1" />
        </label>
        <button className="bg-black text-white text-sm px-3 py-2 rounded" type="submit">Add</button>
      </form>
      <div className="border rounded divide-y bg-white">
        {items.length === 0 && <div className="p-3 text-gray-500">No listings yet.</div>}
        {items.map(i => (
          <div key={i.id} className="p-3 flex items-center justify-between">
            <div>
              <div className="font-medium">{i.title}</div>
              <div className="text-xs text-gray-500">{new Date(i.created_at).toLocaleString()}</div>
            </div>
            <div className="tabular-nums">{i.price}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

