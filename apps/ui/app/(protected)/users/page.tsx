"use client"
import { useEffect, useState } from 'react'

type User = { id: number; discord_id: string; username?: string | null; wallet_balance: number; escrow_balance: number; frozen: boolean; created_at: string }

export default function UsersPage() {
  const [items, setItems] = useState<User[]>([])
  const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL || process.env.NEXT_PUBLIC_API_URL || ''
  useEffect(() => {
    fetch(`${apiBase}/users`).then(r=>r.json()).then(d => setItems(d.items || [])).catch(()=>{})
  }, [])
  return (
    <main className="space-y-4">
      <h1 className="text-2xl font-semibold">Users</h1>
      <div className="border rounded bg-white divide-y">
        {items.length === 0 && <div className="p-3 text-gray-500">No users yet.</div>}
        {items.map(u => (
          <div key={u.id} className="p-3 flex items-center justify-between text-sm">
            <div>
              <div className="font-medium">{u.username || u.discord_id}</div>
              <div className="text-xs text-gray-500">{u.discord_id}</div>
            </div>
            <div className="tabular-nums">{u.wallet_balance}</div>
          </div>
        ))}
      </div>
    </main>
  )
}
