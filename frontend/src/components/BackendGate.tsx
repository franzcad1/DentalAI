import React, { useEffect, useState, useRef } from 'react'
import { Stethoscope, Calendar, Bell, MessageSquare, Users } from 'lucide-react'
import { api } from '@/lib/api'


const FEATURES = [
  { icon: Calendar, label: 'Schedule', desc: 'View & manage appointments' },
  { icon: Bell, label: 'Recalls', desc: 'Overdue patient outreach' },
  { icon: Users, label: 'Patients', desc: 'Patient directory & records' },
  { icon: MessageSquare, label: 'AI Chat', desc: 'Book, search & draft via AI' },
]

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
      <div className="fixed inset-0 z-[9999] flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
        <div className="w-full max-w-lg rounded-2xl border border-surface-border bg-surface-card shadow-2xl">
          {/* Header */}
          <div className="flex items-center gap-4 border-b border-surface-border px-6 py-5">
            <div className="flex h-12 w-12 flex-shrink-0 items-center justify-center rounded-xl bg-accent">
              <Stethoscope className="h-6 w-6 text-white" />
            </div>
            <div>
              <h1 className="text-lg font-semibold text-slate-100">Welcome to DentalAI</h1>
              <p className="text-sm text-slate-400">A mock dental practice management system</p>
            </div>
          </div>

          {/* Body */}
          <div className="px-6 py-5 space-y-4">
            <p className="text-sm text-slate-300 leading-relaxed">
              This is a portfolio project simulating a real dental practice platform — built with
              a <span className="text-slate-100 font-medium">FastAPI + SQLite</span> backend,
              a <span className="text-slate-100 font-medium">React + TypeScript</span> frontend,
              and an <span className="text-slate-100 font-medium">AI agent</span> powered by Groq.
            </p>

            <div className="grid grid-cols-2 gap-2">
              {FEATURES.map(({ icon: Icon, label, desc }) => (
                <div key={label} className="flex items-start gap-2.5 rounded-lg border border-surface-border bg-surface-base p-3">
                  <Icon className="h-4 w-4 text-accent flex-shrink-0 mt-0.5" />
                  <div>
                    <p className="text-xs font-medium text-slate-200">{label}</p>
                    <p className="text-xs text-slate-500">{desc}</p>
                  </div>
                </div>
              ))}
            </div>

            {/* Loading status */}
            <div className="flex items-start gap-2.5 rounded-lg border border-yellow-500/20 bg-yellow-500/5 px-4 py-3">
              <span className="mt-0.5 h-2 w-2 flex-shrink-0 rounded-full bg-yellow-400 animate-pulse" />
              <p className="text-xs text-yellow-300/80 leading-relaxed">
                The backend is hosted on Render's free tier and may take
                <span className="font-medium text-yellow-300"> up to 60 seconds</span> to wake up on first load.
                The AI agent will be ready once it's online.
              </p>
            </div>
            {showAdBlockHint && (
              <p className="text-xs text-slate-500 leading-relaxed">
                Taking longer than expected? An ad blocker or privacy extension may be blocking the backend. Try disabling it or opening in a private window.
              </p>
            )}
          </div>

          {/* Footer */}
          <div className="flex items-center justify-between border-t border-surface-border px-6 py-4">
            <p className="text-xs text-slate-600">Built by Franz · Portfolio 2026</p>
            <div className="flex items-center gap-2 text-xs text-slate-400">
              <svg className="h-3.5 w-3.5 animate-spin text-yellow-400" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Connecting to backend… <span className="tabular-nums text-slate-500">{elapsed}s</span>
            </div>
          </div>
        </div>
      </div>
    </>
  )
}
