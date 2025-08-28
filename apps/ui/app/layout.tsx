import './globals.css'
import { ReactNode } from 'react'

export const metadata = {
  title: 'Coin Economy Panel',
  description: 'Admin & Operator Console',
}

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        {children}
      </body>
    </html>
  )
}

