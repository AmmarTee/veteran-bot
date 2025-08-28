"use client"
import { signIn } from 'next-auth/react'

export default function LoginPage() {
  return (
    <main className="min-h-screen flex items-center justify-center">
      <div className="bg-white shadow rounded p-8 w-full max-w-sm text-center">
        <h1 className="text-2xl font-semibold mb-2">Sign in</h1>
        <p className="text-sm text-gray-500 mb-6">Use Discord to access the panel.</p>
        <button
          className="w-full bg-indigo-600 hover:bg-indigo-700 text-white rounded py-2"
          onClick={() => signIn('discord')}
        >
          Continue with Discord
        </button>
      </div>
    </main>
  )
}

