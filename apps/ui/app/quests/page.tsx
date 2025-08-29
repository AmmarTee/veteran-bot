"use client"
import { useEffect, useState } from 'react'

const guildId = process.env.NEXT_PUBLIC_GUILD_ID || ''
const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL || process.env.NEXT_PUBLIC_API_URL || ''

type Quest = { id: number; title: string; reward: number }

export default function QuestsPage() {
  const [quests, setQuests] = useState<Quest[]>([])
  const [title, setTitle] = useState('')
  const [reward, setReward] = useState('')

  async function load() {
    if (!guildId) return
    const res = await fetch(`${apiBase}/quests/${guildId}`, { cache: 'no-store' }).catch(()=>null)
    if (res && res.ok) setQuests(await res.json())
  }
  useEffect(() => { load() }, [])

  async function addQuest(e: React.FormEvent) {
    e.preventDefault()
    await fetch(`${apiBase}/quests/${guildId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, reward: Number(reward) })
    }).catch(()=>null)
    setTitle(''); setReward(''); load()
  }

  return (
    <div className="space-y-8">
      <h1 className="text-xl font-semibold">Quests</h1>
      <ul className="space-y-2">
        {quests.map(q => (
          <li key={q.id} className="bg-white shadow rounded p-2 flex justify-between">
            <span>{q.title}</span>
            <span className="text-sm text-gray-500">{q.reward} coins</span>
          </li>
        ))}
        {quests.length === 0 && <li className="text-gray-600">No quests yet.</li>}
      </ul>
      <form onSubmit={addQuest} className="space-y-2 max-w-md bg-white p-4 rounded shadow">
        <h2 className="font-medium">Add Quest</h2>
        <input className="border rounded px-2 py-1 w-full" placeholder="Title" value={title} onChange={e=>setTitle(e.target.value)} required />
        <input type="number" className="border rounded px-2 py-1 w-full" placeholder="Reward" value={reward} onChange={e=>setReward(e.target.value)} required />
        <button type="submit" className="bg-black text-white text-sm px-3 py-2 rounded">Add</button>
      </form>
    </div>
  )
}
