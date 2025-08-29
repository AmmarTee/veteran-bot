import Link from 'next/link'

export default function Nav() {
  const items = [
    { href: '/', label: 'Dashboard' },
    { href: '/users', label: 'Users' },
    { href: '/marketplace/listings', label: 'Listings' },
    { href: '/quests', label: 'Quests' },
    { href: '/settings', label: 'Settings' }
  ]
  return (
    <nav className="bg-white border-b">
      <div className="max-w-6xl mx-auto px-4 h-12 flex items-center space-x-4">
        {items.map((i) => (
          <Link key={i.href} className="text-sm text-gray-700 hover:text-black" href={i.href}>{i.label}</Link>
        ))}
      </div>
    </nav>
  )
}

