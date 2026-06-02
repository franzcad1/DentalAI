/**
 * Agent Log View — live event feed.
 *
 * Polls GET /events every 10 seconds. New events animate in at the
 * top of the list. Each row shows the event type, payload fields,
 * and timestamp.
 */
import { useState, useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Activity, Wifi, WifiOff } from 'lucide-react'
import { api, type DentalEvent } from '@/lib/api'
import { eventTypeColor } from '@/lib/utils'
import { cn } from '@/lib/utils'

// ─── Event row ────────────────────────────────────────────────────────────────

function EventRow({ event, isNew }: { event: DentalEvent; isNew: boolean }) {
  const ts = new Date(event.fired_at)
  const timeStr = ts.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
  const dateStr = ts.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })

  // Extract human-readable context from payload
  const contextParts: string[] = []
  const p = event.payload
  if (p.patient_id) contextParts.push(`patient #${p.patient_id}`)
  if (p.appointment_id) contextParts.push(`appt #${p.appointment_id}`)
  if (p.recall_id) contextParts.push(`recall #${p.recall_id}`)
  if (p.recall_type) contextParts.push(String(p.recall_type))
  if (p.due) contextParts.push(`due ${p.due}`)
  if (p.start_time) {
    const t = new Date(String(p.start_time))
    contextParts.push(
      t.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: true })
    )
  }
  if (p.booked_via) contextParts.push(`via ${p.booked_via}`)

  return (
    <div
      className={cn(
        'flex items-start gap-4 border-b border-surface-border px-5 py-3.5 hover:bg-surface-raised/50 transition-colors',
        isNew && 'animate-slide-in-top bg-accent/5'
      )}
    >
      {/* Event type */}
      <div className="min-w-[200px] flex-shrink-0">
        <p className={cn('text-sm font-mono font-medium', eventTypeColor(event.event_type))}>
          {event.event_type}
        </p>
        <p className="mt-0.5 text-[11px] text-slate-600">
          #{event.id} · {event.status}
        </p>
      </div>

      {/* Context */}
      <div className="flex-1 min-w-0">
        <p className="text-sm text-slate-300 truncate">
          {contextParts.length > 0 ? contextParts.join(' · ') : '—'}
        </p>
        {Object.keys(p).length > 0 && (
          <p className="mt-0.5 truncate text-[11px] text-slate-600 font-mono">
            {Object.entries(p)
              .slice(0, 4)
              .map(([k, v]) => `${k}=${v}`)
              .join(' | ')}
          </p>
        )}
      </div>

      {/* Timestamp */}
      <div className="flex-shrink-0 text-right">
        <p className="text-xs font-mono text-slate-400">{timeStr}</p>
        <p className="text-[11px] text-slate-600">{dateStr}</p>
      </div>
    </div>
  )
}

// ─── Main view ────────────────────────────────────────────────────────────────

export function AgentLogView() {
  const [newIds, setNewIds] = useState<Set<number>>(new Set())
  const prevIdsRef = useRef<Set<number>>(new Set())
  const [typeFilter, setTypeFilter] = useState<string>('')

  const { data, isLoading, error, isFetching } = useQuery({
    queryKey: ['events', typeFilter],
    queryFn: () =>
      api.getEvents({ limit: 50, event_type: typeFilter || undefined }),
    refetchInterval: 10_000, // poll every 10 seconds
    refetchIntervalInBackground: false,
  })

  const events: DentalEvent[] = data ?? []

  // Detect genuinely new events on each refetch
  useEffect(() => {
    const currentIds = new Set(events.map((e) => e.id))
    const fresh = new Set<number>()
    for (const id of currentIds) {
      if (!prevIdsRef.current.has(id)) fresh.add(id)
    }
    if (fresh.size > 0) {
      setNewIds(fresh)
      setTimeout(() => setNewIds(new Set()), 3000) // clear highlight after 3s
    }
    prevIdsRef.current = currentIds
  }, [events])

  const EVENT_TYPES = [
    '',
    'appointment.booked',
    'appointment.reminder',
    'recall.due',
  ]

  return (
    <div className="flex h-screen flex-col">
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-surface-border px-6 py-4">
        <Activity className="h-5 w-5 text-accent" />
        <div>
          <h1 className="text-base font-semibold text-slate-100">Agent Log</h1>
          <p className="text-xs text-slate-400">Live event feed · polls every 10 s</p>
        </div>

        {/* Connection indicator */}
        <div className="ml-auto flex items-center gap-2">
          {error ? (
            <div className="flex items-center gap-1.5 text-xs text-red-400">
              <WifiOff className="h-3.5 w-3.5" />
              Disconnected
            </div>
          ) : (
            <div className="flex items-center gap-1.5 text-xs text-green-400">
              <Wifi className={cn('h-3.5 w-3.5', isFetching && 'animate-pulse')} />
              {isFetching ? 'Polling…' : 'Live'}
            </div>
          )}
        </div>
      </div>

      {/* Filter strip */}
      <div className="flex items-center gap-2 border-b border-surface-border px-6 py-3">
        <span className="text-xs text-slate-500 mr-1">Filter:</span>
        {EVENT_TYPES.map((t) => (
          <button
            key={t}
            onClick={() => setTypeFilter(t)}
            className={cn(
              'rounded-full px-3 py-1 text-xs font-medium transition-colors',
              typeFilter === t
                ? 'bg-accent text-white'
                : 'border border-surface-border text-slate-400 hover:bg-surface-raised hover:text-slate-200'
            )}
          >
            {t || 'All events'}
          </button>
        ))}
        {events.length > 0 && (
          <span className="ml-auto text-xs text-slate-500">
            {events.length} event{events.length !== 1 ? 's' : ''}
          </span>
        )}
      </div>

      {/* Event list */}
      <div className="flex-1 overflow-y-auto">
        {/* Loading */}
        {isLoading && (
          <div className="space-y-px pt-px">
            {[...Array(8)].map((_, i) => (
              <div
                key={i}
                className="h-14 animate-pulse border-b border-surface-border bg-surface-card"
              />
            ))}
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="m-6 rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-400">
            Failed to load events: {String(error)}
          </div>
        )}

        {/* Empty */}
        {!isLoading && events.length === 0 && !error && (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <Activity className="mb-3 h-10 w-10 text-slate-600" />
            <p className="text-slate-400">No events yet</p>
            <p className="mt-1 text-xs text-slate-600">
              Events appear here as the scheduler runs and appointments are booked
            </p>
          </div>
        )}

        {/* Rows */}
        {!isLoading &&
          events.map((event) => (
            <EventRow key={event.id} event={event} isNew={newIds.has(event.id)} />
          ))}
      </div>
    </div>
  )
}
