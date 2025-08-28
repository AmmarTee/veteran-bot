import LiveFeed from '../../components/LiveFeed'

export default function Dashboard() {
  return (
    <main className="space-y-6">
      <h1 className="text-2xl font-semibold">Dashboard</h1>
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="bg-white shadow rounded p-4">Volume 24h
          <div className="text-2xl font-bold">—</div>
        </div>
        <div className="bg-white shadow rounded p-4">Fees Burned
          <div className="text-2xl font-bold">—</div>
        </div>
        <div className="bg-white shadow rounded p-4">Pending Escrows
          <div className="text-2xl font-bold">—</div>
        </div>
        <div className="bg-white shadow rounded p-4">Fulfil Success
          <div className="text-2xl font-bold">—</div>
        </div>
      </div>
      <LiveFeed />
    </main>
  )
}
