import React, { useEffect, useState, useRef } from 'react'
import { api } from '@/lib/api'

export const BackendReadyContext = React.createContext(false)

export function BackendGate({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const [elapsed, setElapsed] = useState(0)
  const [showAdBlockHint, setShowAdBlockHint] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    const id = setInterval(() => setElapsed(s => s + 1), 1000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    const id = setTimeout(() => setShowAdBlockHint(true), 60_000)
    return () => clearTimeout(id)
  }, [])

  useEffect(() => {
    let cancelled = false

    async function check() {
      try {
        await api.getHealth()
        if (!cancelled) setReady(true)
      } catch {
        if (!cancelled) {
          timerRef.current = setTimeout(() => {
            if (!cancelled) setAttempt(a => a + 1)
          }, 2500)
        }
      }
    }

    check()
    return () => {
      cancelled = true
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [attempt])

  if (ready) return (
    <BackendReadyContext.Provider value={true}>
      {children}
    </BackendReadyContext.Provider>
  )

  return (
    <>
      {children}
      {/* Bottom-right toast — non-blocking */}
      <div className="fixed bottom-4 right-4 z-[9999] w-72 rounded-xl border border-yellow-500/20 bg-surface-card shadow-2xl">
        <div className="flex items-start gap-3 px-4 py-3">
          <svg className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 animate-spin text-yellow-400" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          <div className="min-w-0">
            <p className="text-xs font-medium text-slate-300">
              Connecting to backend… <span className="tabular-nums text-slate-500">{elapsed}s</span>
            </p>
            <p className="mt-0.5 text-xs text-slate-500 leading-relaxed">
              Render's free tier may take up to 60s to wake up.
            </p>
            {showAdBlockHint && (
              <p className="mt-1 text-xs text-slate-600 leading-relaxed">
                Still loading? Try disabling your ad blocker or open in a private window.
              </p>
            )}
          </div>
        </div>
      </div>
    </>
  )
}
