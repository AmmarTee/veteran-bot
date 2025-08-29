"use client"
import { useEffect, useState } from 'react'

const guildId = process.env.NEXT_PUBLIC_GUILD_ID || ''

export default function SettingsPage() {
  const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL || process.env.NEXT_PUBLIC_API_URL || ''
  const [announcementChannel, setAnnouncementChannel] = useState('')
  const [announcementInterval, setAnnouncementInterval] = useState('')
  const [messageChannel, setMessageChannel] = useState('')
  const [messageContent, setMessageContent] = useState('')

  useEffect(() => { load() }, [])

  async function load() {
    if (!guildId) return
    try {
      const res = await fetch(`${apiBase}/config/${guildId}`, { cache: 'no-store' })
      if (!res.ok) return
      const data = await res.json()
      setAnnouncementChannel(data.announcementsChannelId || '')
      setAnnouncementInterval(data.announcementIntervalMinutes ? String(data.announcementIntervalMinutes) : '')
    } catch {}
  }

  async function save(e: React.FormEvent) {
    e.preventDefault()
    if (!guildId) return
    try {
      await fetch(`${apiBase}/config/${guildId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          announcementsChannelId: announcementChannel || null,
          announcementIntervalMinutes: announcementInterval ? Number(announcementInterval) : null,
        })
      })
    } catch {}
  }

  async function sendMessage(e: React.FormEvent) {
    e.preventDefault()
    try {
      await fetch(`${apiBase}/admin/message`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ channel_id: messageChannel, content: messageContent })
      })
      setMessageContent('')
    } catch {}
  }

  return (
    <div className="space-y-8">
      <h1 className="text-xl font-semibold">Settings</h1>

      <form onSubmit={save} className="space-y-4 max-w-md bg-white p-4 rounded shadow">
        <h2 className="font-medium">Announcements</h2>
        <label className="flex flex-col text-sm">
          <span className="text-gray-600">Channel ID</span>
          <input className="border rounded px-2 py-1" value={announcementChannel} onChange={e => setAnnouncementChannel(e.target.value)} />
        </label>
        <label className="flex flex-col text-sm">
          <span className="text-gray-600">Interval (minutes)</span>
          <input type="number" className="border rounded px-2 py-1" value={announcementInterval} onChange={e => setAnnouncementInterval(e.target.value)} min={0} />
        </label>
        <button type="submit" className="bg-black text-white text-sm px-3 py-2 rounded">Save</button>
      </form>

      <form onSubmit={sendMessage} className="space-y-4 max-w-md bg-white p-4 rounded shadow">
        <h2 className="font-medium">Post Message</h2>
        <label className="flex flex-col text-sm">
          <span className="text-gray-600">Channel ID</span>
          <input className="border rounded px-2 py-1" value={messageChannel} onChange={e => setMessageChannel(e.target.value)} required />
        </label>
        <label className="flex flex-col text-sm">
          <span className="text-gray-600">Message</span>
          <textarea className="border rounded px-2 py-1" value={messageContent} onChange={e => setMessageContent(e.target.value)} required />
        </label>
        <button type="submit" className="bg-black text-white text-sm px-3 py-2 rounded">Send</button>
      </form>
    </div>
  )
}
