/**
 * Schedule View — today's appointments with full CRUD.
 *
 * Actions:
 *   + New Appointment  — form dialog: patient, provider, type, date/time
 *   Status badge click — cycle status inline (confirmed → completed → no_show → cancelled)
 *   Notes icon click   — edit notes inline
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  CalendarDays, Clock, RefreshCw, User, Stethoscope,
  Plus, FileText, Check, X,
} from 'lucide-react'
import {
  api,
  type Appointment, type AppointmentStatus,
  type Patient, type Provider,
} from '@/lib/api'
import { formatTime, statusColors, todayISO } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import type { BadgeProps } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Dialog, DialogContent, DialogHeader,
  DialogTitle, DialogDescription,
} from '@/components/ui/dialog'

// ─── Helpers ─────────────────────────────────────────────────────────────────

function statusVariant(s: AppointmentStatus): BadgeProps['variant'] {
  const m: Record<AppointmentStatus, BadgeProps['variant']> = {
    completed: 'completed', confirmed: 'confirmed',
    pending: 'pending', cancelled: 'cancelled', no_show: 'no_show',
  }
  return m[s]
}

function statusLabel(s: AppointmentStatus) {
  return s.replace('_', ' ').replace(/^\w/, c => c.toUpperCase())
}

// Clicking cycles through logical next states
const NEXT_STATUS: Record<AppointmentStatus, AppointmentStatus> = {
  pending: 'confirmed',
  confirmed: 'completed',
  completed: 'no_show',
  no_show: 'cancelled',
  cancelled: 'pending',
}

// ─── New Appointment Form ─────────────────────────────────────────────────────

interface NewApptFormProps {
  open: boolean
  onClose: () => void
  patients: Patient[]
  providers: Provider[]
  appointmentTypes: { id: number; name: string; duration_minutes: number }[]
  locations: { id: number; name: string }[]
  onCreated: () => void
}

function NewAppointmentDialog({
  open, onClose, patients, providers, appointmentTypes, locations, onCreated,
}: NewApptFormProps) {
  const today = todayISO()
  const [form, setForm] = useState({
    patient_id: '',
    provider_id: '',
    location_id: '',
    appointment_type_id: '',
    date: today,
    time: '09:00',
    notes: '',
  })
  const [error, setError] = useState('')

  const mutation = useMutation({
    mutationFn: () => {
      const type = appointmentTypes.find(t => t.id === Number(form.appointment_type_id))
      const startISO = `${form.date}T${form.time}:00`
      const start = new Date(startISO)
      const end = new Date(start.getTime() + (type?.duration_minutes ?? 30) * 60_000)
      return api.createAppointment({
        patient_id: Number(form.patient_id),
        provider_id: Number(form.provider_id),
        location_id: Number(form.location_id),
        appointment_type_id: Number(form.appointment_type_id),
        start_time: startISO,
        end_time: end.toISOString().slice(0, 19),
        status: 'confirmed',
        notes: form.notes || undefined,
      })
    },
    onSuccess: () => {
      onCreated()
      onClose()
      setForm({ patient_id: '', provider_id: '', location_id: '', appointment_type_id: '', date: today, time: '09:00', notes: '' })
      setError('')
    },
    onError: (e: Error) => setError(e.message),
  })

  function set(key: string, val: string) {
    setForm(f => ({ ...f, [key]: val }))
    setError('')
  }

  const canSubmit = form.patient_id && form.provider_id && form.location_id && form.appointment_type_id

  return (
    <Dialog open={open} onOpenChange={v => { if (!v) onClose() }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New Appointment</DialogTitle>
          <DialogDescription>Schedule a new appointment. End time is calculated automatically.</DialogDescription>
        </DialogHeader>

        <div className="space-y-3 mt-1">
          {/* Patient */}
          <div>
            <label className="mb-1 block text-xs text-slate-400">Patient</label>
            <select
              value={form.patient_id}
              onChange={e => set('patient_id', e.target.value)}
              className="w-full rounded-md border border-surface-border bg-surface-raised px-3 py-2 text-sm text-slate-200 focus:outline-none focus:ring-2 focus:ring-accent"
            >
              <option value="">Select patient…</option>
              {patients.map(p => (
                <option key={p.id} value={p.id}>{p.first_name} {p.last_name}</option>
              ))}
            </select>
          </div>

          {/* Provider */}
          <div>
            <label className="mb-1 block text-xs text-slate-400">Provider</label>
            <select
              value={form.provider_id}
              onChange={e => set('provider_id', e.target.value)}
              className="w-full rounded-md border border-surface-border bg-surface-raised px-3 py-2 text-sm text-slate-200 focus:outline-none focus:ring-2 focus:ring-accent"
            >
              <option value="">Select provider…</option>
              {providers.map(p => (
                <option key={p.id} value={p.id}>Dr. {p.first_name} {p.last_name}</option>
              ))}
            </select>
          </div>

          {/* Location + Type row */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block text-xs text-slate-400">Location</label>
              <select
                value={form.location_id}
                onChange={e => set('location_id', e.target.value)}
                className="w-full rounded-md border border-surface-border bg-surface-raised px-3 py-2 text-sm text-slate-200 focus:outline-none focus:ring-2 focus:ring-accent"
              >
                <option value="">Select…</option>
                {locations.map(l => (
                  <option key={l.id} value={l.id}>{l.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs text-slate-400">Type</label>
              <select
                value={form.appointment_type_id}
                onChange={e => set('appointment_type_id', e.target.value)}
                className="w-full rounded-md border border-surface-border bg-surface-raised px-3 py-2 text-sm text-slate-200 focus:outline-none focus:ring-2 focus:ring-accent"
              >
                <option value="">Select…</option>
                {appointmentTypes.map(t => (
                  <option key={t.id} value={t.id}>{t.name} ({t.duration_minutes} min)</option>
                ))}
              </select>
            </div>
          </div>

          {/* Date + Time */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block text-xs text-slate-400">Date</label>
              <Input type="date" value={form.date} onChange={e => set('date', e.target.value)} />
            </div>
            <div>
              <label className="mb-1 block text-xs text-slate-400">Start time</label>
              <Input type="time" value={form.time} onChange={e => set('time', e.target.value)} />
            </div>
          </div>

          {/* Notes */}
          <div>
            <label className="mb-1 block text-xs text-slate-400">Notes (optional)</label>
            <Input
              placeholder="Clinical or scheduling notes…"
              value={form.notes}
              onChange={e => set('notes', e.target.value)}
            />
          </div>

          {error && <p className="text-xs text-red-400">{error}</p>}

          <div className="flex justify-end gap-2 pt-1">
            <Button variant="ghost" size="sm" onClick={onClose}>Cancel</Button>
            <Button
              size="sm"
              disabled={!canSubmit || mutation.isPending}
              onClick={() => mutation.mutate()}
            >
              {mutation.isPending ? 'Booking…' : 'Book Appointment'}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

// ─── Notes editor ─────────────────────────────────────────────────────────────

function NotesCell({ appt }: { appt: Appointment }) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(appt.notes ?? '')

  const mutation = useMutation({
    mutationFn: (notes: string) => api.updateAppointment(appt.id, { notes }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['appointments'] })
      setEditing(false)
    },
  })

  if (editing) {
    return (
      <div className="flex items-center gap-1">
        <Input
          autoFocus
          value={draft}
          onChange={e => setDraft(e.target.value)}
          className="h-7 text-xs"
          onKeyDown={e => {
            if (e.key === 'Enter') mutation.mutate(draft)
            if (e.key === 'Escape') setEditing(false)
          }}
        />
        <button onClick={() => mutation.mutate(draft)} className="text-green-400 hover:text-green-300"><Check className="h-3.5 w-3.5" /></button>
        <button onClick={() => setEditing(false)} className="text-slate-500 hover:text-slate-300"><X className="h-3.5 w-3.5" /></button>
      </div>
    )
  }

  return (
    <button
      onClick={() => setEditing(true)}
      className="group flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-300 transition-colors"
      title="Click to edit notes"
    >
      <FileText className="h-3 w-3" />
      <span className="truncate max-w-[120px]">{appt.notes || 'Add note…'}</span>
    </button>
  )
}

// ─── Main view ────────────────────────────────────────────────────────────────

export function ScheduleView() {
  const today = todayISO()
  const qc = useQueryClient()
  const [showNewAppt, setShowNewAppt] = useState(false)

  const apptQuery   = useQuery({ queryKey: ['appointments', today], queryFn: () => api.getAppointments({ date: today, limit: 200 }) })
  const patientQuery = useQuery({ queryKey: ['patients'], queryFn: () => api.getPatients({ limit: 200 }) })
  const providerQuery = useQuery({ queryKey: ['providers'], queryFn: () => api.getProviders() })
  const typeQuery    = useQuery({ queryKey: ['appointment_types'], queryFn: () => api.getAppointmentTypes() })
  const locationQuery = useQuery({ queryKey: ['locations'], queryFn: () => api.getLocations() })

  const statusMutation = useMutation({
    mutationFn: ({ id, status }: { id: number; status: AppointmentStatus }) =>
      api.updateAppointment(id, { status }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['appointments'] }),
  })

  const isLoading = apptQuery.isLoading || patientQuery.isLoading || providerQuery.isLoading
  const error = apptQuery.error || patientQuery.error || providerQuery.error

  const patientMap  = new Map((patientQuery.data?.data.items ?? []).map(p => [p.id, p]))
  const providerMap = new Map((providerQuery.data?.data.items ?? []).map(p => [p.id, p]))
  const typeMap     = new Map((typeQuery.data?.data.items ?? []).map(t => [t.id, t.name]))

  const appointments = [...(apptQuery.data?.data.items ?? [])].sort(
    (a, b) => new Date(a.start_time).getTime() - new Date(b.start_time).getTime()
  )

  return (
    <div className="p-6">
      {/* Header */}
      <div className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <CalendarDays className="h-6 w-6 text-accent" />
          <div>
            <h1 className="text-xl font-semibold text-slate-100">Today's Schedule</h1>
            <p className="text-sm text-slate-400">
              {new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' })}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => apptQuery.refetch()}
            className="flex items-center gap-1.5 rounded-lg border border-surface-border px-3 py-2 text-xs text-slate-400 hover:bg-surface-raised hover:text-slate-200 transition-colors"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${apptQuery.isFetching ? 'animate-spin' : ''}`} />
            Refresh
          </button>
          <Button size="sm" onClick={() => setShowNewAppt(true)} className="gap-1.5">
            <Plus className="h-4 w-4" /> New Appointment
          </Button>
        </div>
      </div>

      {/* Stats strip */}
      {!isLoading && !error && (
        <div className="mb-6 grid grid-cols-4 gap-3">
          {(['confirmed', 'completed', 'no_show', 'cancelled'] as AppointmentStatus[]).map(s => {
            const count = appointments.filter(a => a.status === s).length
            const colors = statusColors(s)
            return (
              <div key={s} className="rounded-lg border border-surface-border bg-surface-card p-3">
                <p className={`text-2xl font-bold ${colors.text}`}>{count}</p>
                <p className="text-xs text-slate-500 capitalize">{statusLabel(s)}</p>
              </div>
            )
          })}
        </div>
      )}

      {isLoading && (
        <div className="space-y-3">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-20 animate-pulse rounded-xl bg-surface-card border border-surface-border" />
          ))}
        </div>
      )}

      {error && (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-400">
          Failed to load: {String(error)}
        </div>
      )}

      {!isLoading && !error && appointments.length === 0 && (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-surface-border py-16 text-center">
          <CalendarDays className="mb-3 h-10 w-10 text-slate-600" />
          <p className="text-slate-400">No appointments today</p>
          <Button size="sm" className="mt-4 gap-1.5" onClick={() => setShowNewAppt(true)}>
            <Plus className="h-3.5 w-3.5" /> Book one now
          </Button>
        </div>
      )}

      {/* Appointment rows */}
      {!isLoading && !error && appointments.length > 0 && (
        <div className="space-y-2">
          {appointments.map(appt => {
            const patient  = patientMap.get(appt.patient_id)
            const provider = providerMap.get(appt.provider_id)
            const typeName = typeMap.get(appt.appointment_type_id) ?? 'Unknown'
            const colors   = statusColors(appt.status)
            const isUpdating = statusMutation.isPending && statusMutation.variables?.id === appt.id

            return (
              <div
                key={appt.id}
                className="flex items-center gap-4 rounded-xl border border-surface-border bg-surface-card p-4 hover:bg-surface-raised transition-colors"
              >
                <div className={`h-12 w-1 flex-shrink-0 rounded-full ${colors.dot}`} />

                {/* Time */}
                <div className="w-20 flex-shrink-0">
                  <p className="text-sm font-semibold text-slate-200">{formatTime(appt.start_time)}</p>
                  <p className="flex items-center gap-1 text-xs text-slate-500">
                    <Clock className="h-3 w-3" />{formatTime(appt.end_time)}
                  </p>
                </div>

                {/* Patient */}
                <div className="flex min-w-0 flex-1 items-center gap-3">
                  <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full bg-surface-raised">
                    <User className="h-4 w-4 text-slate-400" />
                  </div>
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-slate-200">
                      {patient ? `${patient.first_name} ${patient.last_name}` : `Patient #${appt.patient_id}`}
                    </p>
                    <p className="truncate text-xs text-slate-500 capitalize">{typeName}</p>
                  </div>
                </div>

                {/* Provider */}
                <div className="hidden w-36 flex-shrink-0 sm:block">
                  <p className="flex items-center gap-1.5 text-xs text-slate-400">
                    <Stethoscope className="h-3 w-3" />
                    {provider ? `Dr. ${provider.last_name}` : `#${appt.provider_id}`}
                  </p>
                </div>

                {/* Notes */}
                <div className="hidden w-36 flex-shrink-0 lg:block">
                  <NotesCell appt={appt} />
                </div>

                {/* Status — click to advance */}
                <button
                  disabled={isUpdating}
                  onClick={() => statusMutation.mutate({ id: appt.id, status: NEXT_STATUS[appt.status] })}
                  title={`Click to mark as ${statusLabel(NEXT_STATUS[appt.status])}`}
                  className="flex-shrink-0 transition-opacity disabled:opacity-50"
                >
                  <Badge variant={statusVariant(appt.status)} className="cursor-pointer hover:opacity-80">
                    <span className={`inline-block h-1.5 w-1.5 rounded-full ${colors.dot}`} />
                    {isUpdating ? '…' : statusLabel(appt.status)}
                  </Badge>
                </button>
              </div>
            )
          })}
        </div>
      )}

      {/* New appointment dialog */}
      <NewAppointmentDialog
        open={showNewAppt}
        onClose={() => setShowNewAppt(false)}
        patients={patientQuery.data?.data.items ?? []}
        providers={providerQuery.data?.data.items ?? []}
        appointmentTypes={typeQuery.data?.data.items ?? []}
        locations={(locationQuery.data?.data.items ?? []).map(l => ({ id: l.id, name: l.name }))}
        onCreated={() => qc.invalidateQueries({ queryKey: ['appointments'] })}
      />
    </div>
  )
}
