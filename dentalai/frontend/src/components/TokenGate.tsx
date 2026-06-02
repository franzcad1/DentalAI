/**
 * Shown when no Bearer token is stored.
 * The backend prints the token on startup — paste it here.
 * Set VITE_DEV_TOKEN in .env to skip this screen entirely.
 */
import { useState } from 'react'
import { Stethoscope } from 'lucide-react'
import { setToken } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

interface Props {
  onAuthenticated: () => void
}

export function TokenGate({ onAuthenticated }: Props) {
  const [value, setValue] = useState('')
  const [error, setError] = useState('')

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const trimmed = value.trim()
    if (!trimmed) {
      setError('Please enter the Bearer token from the server log.')
      return
    }
    setToken(trimmed)
    onAuthenticated()
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-surface-base px-4">
      <div className="w-full max-w-md">
        {/* Logo */}
        <div className="mb-8 flex flex-col items-center gap-3">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-accent shadow-lg shadow-accent/30">
            <Stethoscope className="h-7 w-7 text-white" />
          </div>
          <div className="text-center">
            <h1 className="text-2xl font-bold text-slate-100">DentalAI</h1>
            <p className="text-sm text-slate-400">Practice Management System</p>
          </div>
        </div>

        {/* Card */}
        <div className="rounded-xl border border-surface-border bg-surface-card p-6 shadow-xl">
          <h2 className="mb-1 text-base font-semibold text-slate-200">Enter dev token</h2>
          <p className="mb-5 text-sm text-slate-400">
            Copy the Bearer token printed in the backend server log on startup.
          </p>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <Input
                type="password"
                placeholder="eyJhbGci..."
                value={value}
                onChange={(e) => {
                  setValue(e.target.value)
                  setError('')
                }}
                className="font-mono text-xs"
                autoFocus
              />
              {error && <p className="mt-1.5 text-xs text-red-400">{error}</p>}
            </div>
            <Button type="submit" className="w-full">
              Continue
            </Button>
          </form>

          <p className="mt-4 text-center text-xs text-slate-600">
            Or set <code className="text-slate-400">VITE_DEV_TOKEN</code> in{' '}
            <code className="text-slate-400">frontend/.env</code> to skip this screen.
          </p>
        </div>
      </div>
    </div>
  )
}
