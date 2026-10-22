import { useState, useEffect } from 'react'
import { Stethoscope, Calendar, Bell, MessageSquare, Users, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'

const STARTUP_KEY = 'dentalai_startup_id'
export const WELCOME_DISMISSED_KEY = 'dentalai_welcome_dismissed'

export function WelcomeModal() {
  const [open, setOpen] = useState(false)

  useEffect(() => {
    // Show the modal whenever the backend has restarted (new startup_id)
    api.getHealth().then(({ startup_id }) => {
      try {
        const seen = localStorage.getItem(STARTUP_KEY)
        if (seen !== startup_id) setOpen(true)
      } catch {
        setOpen(true)
      }
    }).catch(() => {
      // Backend offline — show modal so cold-start notice is visible
      try {
        if (!localStorage.getItem(STARTUP_KEY)) setOpen(true)
      } catch {
        setOpen(true)
      }
    })
  }, [])

  function dismiss() {
    api.getHealth().then(({ startup_id }) => {
      try { localStorage.setItem(STARTUP_KEY, startup_id) } catch {}
    }).catch(() => {})
    try { localStorage.setItem(WELCOME_DISMISSED_KEY, '1') } catch {}
    setOpen(false)
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
      <div className="relative w-full max-w-lg rounded-2xl border border-surface-border bg-surface-card shadow-2xl">
        {/* Close */}
        <button
          onClick={dismiss}
          className="absolute right-4 top-4 text-red-500 hover:text-red-400 transition-colors"
        >
          <X className="h-4 w-4" />
        </button>

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

          {/* Features */}
          <div className="grid grid-cols-2 gap-2">
            {[
              { icon: Calendar, label: 'Schedule', desc: 'View & manage appointments' },
              { icon: Bell, label: 'Recalls', desc: 'Overdue patient outreach' },
              { icon: Users, label: 'Patients', desc: 'Patient directory & records' },
              { icon: MessageSquare, label: 'AI Chat', desc: 'Book, search & draft via AI' },
            ].map(({ icon: Icon, label, desc }) => (
              <div key={label} className="flex items-start gap-2.5 rounded-lg border border-surface-border bg-surface-base p-3">
                <Icon className="h-4 w-4 text-accent flex-shrink-0 mt-0.5" />
                <div>
                  <p className="text-xs font-medium text-slate-200">{label}</p>
                  <p className="text-xs text-slate-500">{desc}</p>
                </div>
              </div>
            ))}
          </div>

          {/* Cold start notice */}
          <div className="flex items-start gap-2.5 rounded-lg border border-yellow-500/20 bg-yellow-500/5 px-4 py-3">
            <span className="mt-0.5 h-2 w-2 flex-shrink-0 rounded-full bg-yellow-400 animate-pulse" />
            <p className="text-xs text-yellow-300/80 leading-relaxed">
              The backend is hosted on Render's free tier and may take
              <span className="font-medium text-yellow-300"> up to 30 seconds</span> to wake up on first load.
              The AI agent will be ready once it's online.
            </p>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-surface-border px-6 py-4">
          <p className="text-xs text-slate-600">Built by Franz · Portfolio 2026</p>
          <Button size="sm" onClick={dismiss} className="gap-2">
            Get Started
          </Button>
        </div>
      </div>
    </div>
  )
}
