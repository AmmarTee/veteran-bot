import './globals.css'
import { ReactNode } from 'react'

export const metadata = {
  title: 'Coin Economy Panel',
  description: 'Admin & Operator Console',
}

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="icon" href="/favicon.svg" type="image/svg+xml" />
      </head>
      <body>
        {children}
      </body>
    </html>
  )
}
