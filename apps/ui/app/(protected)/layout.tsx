import { ReactNode } from 'react'
import { getServerSession } from 'next-auth'
import { authOptions } from '../lib/auth'
import { redirect } from 'next/navigation'
import Nav from '../../components/Nav'

export default async function ProtectedLayout({ children }: { children: ReactNode }) {
  const session = await getServerSession(authOptions)
  if (!session) redirect('/login')
  return (
    <section>
      <Nav />
      <div className="max-w-6xl mx-auto p-4">
        {children}
      </div>
    </section>
  )
}
