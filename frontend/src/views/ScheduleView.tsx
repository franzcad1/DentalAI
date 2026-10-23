/**
 * Schedule View — today's appointments with full CRUD.
 *
 * Actions:
 *   + New Appointment  — form dialog: patient, provider, type, date/time
 *   Status badge click — cycle status inline (confirmed → completed → no_show → cancelled)
 *   Notes icon click   — edit notes inline
 */
import { useState, useEffect, useRef, useLayoutEffect } from 'react'
import { startScheduleTour, destroyTourIfActive } from '@/hooks/useScheduleTour'
import { WELCOME_DISMISSED_KEY } from '@/components/WelcomeModal'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  CalendarDays, Clock, RefreshCw, User, Stethoscope,
  Plus, FileText, Check, X, HelpCircle,
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
  initialDate?: string
  initialTime?: string
  initialProviderId?: number
}

function NewAppointmentDialog({
  open, onClose, patients, providers, appointmentTypes, locations, onCreated,
  initialDate, initialTime, initialProviderId,
}: NewApptFormProps) {
  const today = todayISO()
  const [form, setForm] = useState({
    patient_id: '',
    provider_id: initialProviderId ? String(initialProviderId) : '',
    location_id: '',
    appointment_type_id: '',
    date: initialDate ?? today,
    time: initialTime ?? '09:00',
    notes: '',
  })
  const [error, setError] = useState('')

  // Sync prefill when dialog opens
  useEffect(() => {
    if (open) setForm(f => ({
      ...f,
      date: initialDate ?? today,
      time: initialTime ?? f.time,
      provider_id: initialProviderId ? String(initialProviderId) : f.provider_id,
    }))
  }, [open, initialDate, initialTime, initialProviderId])

  const mutation = useMutation({
    mutationFn: () => {
      const type = appointmentTypes.find(t => t.id === Number(form.appointment_type_id))
      const startISO = `${form.date}T${form.time}:00`
      const durationMins = type?.duration_minutes ?? 30
      const [sh, sm] = form.time.split(':').map(Number)
      const endTotalMins = sh * 60 + sm + durationMins
      const endH = Math.floor(endTotalMins / 60).toString().padStart(2, '0')
      const endM = (endTotalMins % 60).toString().padStart(2, '0')
      const endISO = `${form.date}T${endH}:${endM}:00`
      if (endTotalMins > 17 * 60) {
        const end = new Date(`${form.date}T${endH}:${endM}:00`)
        const endStr = end.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
        throw new Error(`This appointment would end at ${endStr}, after the 5:00 PM closing time. Choose an earlier start time.`)
      }
      return api.createAppointment({
        patient_id: Number(form.patient_id),
        provider_id: Number(form.provider_id),
        location_id: Number(form.location_id),
        appointment_type_id: Number(form.appointment_type_id),
        start_time: startISO,
        end_time: endISO,
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

// ─── Edit Appointment Dialog ──────────────────────────────────────────────────

interface EditApptDialogProps {
  appt: Appointment | null
  onClose: () => void
  providers: Provider[]
  appointmentTypes: { id: number; name: string; duration_minutes: number }[]
  onSaved: () => void
}

function EditAppointmentDialog({ appt, onClose, providers, appointmentTypes, onSaved }: EditApptDialogProps) {
  const [form, setForm] = useState({
    status: appt?.status ?? 'confirmed' as AppointmentStatus,
    provider_id: String(appt?.provider_id ?? ''),
    appointment_type_id: String(appt?.appointment_type_id ?? ''),
    date: appt ? appt.start_time.slice(0, 10) : '',
    time: appt ? appt.start_time.slice(11, 16) : '',
    end_time: appt ? appt.end_time.slice(11, 16) : '',
    notes: appt?.notes ?? '',
  })
  const [error, setError] = useState('')
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [statusOpen, setStatusOpen] = useState(false)

  // Reset form when appt changes
  useEffect(() => {
    if (appt) setForm({
      status: appt.status,
      provider_id: String(appt.provider_id),
      appointment_type_id: String(appt.appointment_type_id),
      date: appt.start_time.slice(0, 10),
      time: appt.start_time.slice(11, 16),
      end_time: appt.end_time.slice(11, 16),
      notes: appt.notes ?? '',
    })
  }, [appt])

  const qcEdit = useQueryClient()

  const mutation = useMutation({
    mutationFn: () => {
      if (!appt) return Promise.reject()
      const startISO = `${form.date}T${form.time}:00`
      const origTime = appt.start_time.slice(11, 16)
      const startChanged = form.time !== origTime
      let endISO: string
      if (startChanged) {
        // start moved — shift end by the same delta
        const [oh, om] = origTime.split(':').map(Number)
        const [sh, sm] = form.time.split(':').map(Number)
        const [eh, em] = form.end_time.split(':').map(Number)
        const deltaMins = (sh * 60 + sm) - (oh * 60 + om)
        const newEndMins = eh * 60 + em + deltaMins
        if (newEndMins > 17 * 60) throw new Error('This appointment would end after 5:00 PM. Choose an earlier start time.')
        endISO = `${form.date}T${Math.floor(newEndMins / 60).toString().padStart(2, '0')}:${(newEndMins % 60).toString().padStart(2, '0')}:00`
      } else {
        endISO = `${form.date}T${form.end_time}:00`
      }
      return api.updateAppointment(appt.id, {
        status: form.status,
        notes: form.notes || undefined,
        start_time: startISO,
        end_time: endISO,
      })
    },
    onSuccess: () => { onSaved(); onClose(); setError('') },
    onError: (e: Error) => setError(e.message),
  })

  const deleteMutation = useMutation({
    mutationFn: () => api.deleteAppointment(appt!.id),
    onSuccess: () => { qcEdit.invalidateQueries({ queryKey: ['appointments'] }); onClose() },
    onError: (e: Error) => setError(e.message),
  })

  function set(key: string, val: string) { setForm(f => ({ ...f, [key]: val })); setError('') }

  const STATUSES: AppointmentStatus[] = ['confirmed', 'completed', 'pending', 'no_show', 'cancelled']

  return (
    <Dialog open={!!appt} onOpenChange={v => { if (!v) onClose() }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit Appointment</DialogTitle>
          <DialogDescription>Update details for this appointment.</DialogDescription>
        </DialogHeader>

        <div className="space-y-3 mt-1">
          {/* Status */}
          <div className="relative">
            <label className="mb-1 block text-xs text-slate-400">Status</label>
            <button
              type="button"
              onClick={() => setStatusOpen(o => !o)}
              className="w-full flex items-center justify-between rounded-md border border-surface-border bg-surface-raised px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent"
            >
              <span className={statusColors(form.status).text}>{statusLabel(form.status)}</span>
              <svg className="h-4 w-4 text-slate-400" viewBox="0 0 20 20" fill="currentColor"><path fillRule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clipRule="evenodd" /></svg>
            </button>
            {statusOpen && (
              <div className="absolute z-50 mt-1 w-full rounded-md border border-surface-border bg-surface-card shadow-lg overflow-hidden">
                {STATUSES.map(s => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => { set('status', s); setStatusOpen(false) }}
                    className={`w-full px-3 py-2 text-sm text-left transition-colors hover:bg-surface-raised ${statusColors(s).text} ${form.status === s ? 'bg-surface-raised' : ''}`}
                  >
                    {statusLabel(s)}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Provider */}
          <div>
            <label className="mb-1 block text-xs text-slate-400">Provider</label>
            <select value={form.provider_id} onChange={e => set('provider_id', e.target.value)}
              className="w-full rounded-md border border-surface-border bg-surface-raised px-3 py-2 text-sm text-slate-200 focus:outline-none focus:ring-2 focus:ring-accent">
              {providers.map(p => <option key={p.id} value={String(p.id)}>Dr. {p.first_name} {p.last_name}</option>)}
            </select>
          </div>

          {/* Type */}
          <div>
            <label className="mb-1 block text-xs text-slate-400">Appointment Type</label>
            <select value={form.appointment_type_id} onChange={e => set('appointment_type_id', e.target.value)}
              className="w-full rounded-md border border-surface-border bg-surface-raised px-3 py-2 text-sm text-slate-200 focus:outline-none focus:ring-2 focus:ring-accent">
              {appointmentTypes.map(t => <option key={t.id} value={String(t.id)}>{t.name} ({t.duration_minutes} min)</option>)}
            </select>
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
            <label className="mb-1 block text-xs text-slate-400">Notes</label>
            <Input placeholder="Clinical or scheduling notes…" value={form.notes} onChange={e => set('notes', e.target.value)} />
          </div>

          {error && <p className="text-xs text-red-400">{error}</p>}

          {confirmDelete ? (
            <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 space-y-2">
              <p className="text-xs text-red-400">Delete this appointment? This cannot be undone.</p>
              <div className="flex gap-2">
                <Button size="sm" variant="destructive" disabled={deleteMutation.isPending} onClick={() => deleteMutation.mutate()}>
                  {deleteMutation.isPending ? 'Deleting…' : 'Yes, delete'}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(false)}>Cancel</Button>
              </div>
            </div>
          ) : (
            <div className="flex items-center justify-between pt-1">
              <Button size="sm" variant="destructive" onClick={() => setConfirmDelete(true)}>Delete</Button>
              <div className="flex gap-2">
                <Button variant="ghost" size="sm" onClick={onClose}>Cancel</Button>
                <Button size="sm" disabled={mutation.isPending} onClick={() => mutation.mutate()}>
                  {mutation.isPending ? 'Saving…' : 'Save Changes'}
                </Button>
              </div>
            </div>
          )}
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

// ─── Dentrix-style appointment grid (desktop only) ───────────────────────────

const GRID_START_H = 8
const GRID_END_H   = 17
const SLOTS_TOTAL  = (GRID_END_H - GRID_START_H) * 6  // 54

function slotTop(isoTime: string, slotH: number): number {
  const d = new Date(isoTime)
  const mins = d.getHours() * 60 + d.getMinutes() - GRID_START_H * 60
  return Math.max(0, (mins / 10) * slotH)
}

function slotHeight(startISO: string, endISO: string, slotH: number): number {
  const mins = (new Date(endISO).getTime() - new Date(startISO).getTime()) / 60_000
  return Math.max(slotH, (mins / 10) * slotH)
}

const GRID_COLORS: Record<AppointmentStatus, string> = {
  confirmed: 'bg-blue-500/25 border-blue-400/50 text-blue-200',
  completed: 'bg-green-500/25 border-green-400/50 text-green-200',
  pending:   'bg-yellow-500/20 border-yellow-400/50 text-yellow-200',
  no_show:   'bg-red-500/20 border-red-400/50 text-red-300',
  cancelled: 'bg-slate-500/15 border-slate-500/30 text-slate-500',
}

interface AppointmentGridProps {
  appointments: Appointment[]
  providers: Provider[]
  patientMap: Map<number, Patient>
  typeMap: Map<number, string>
  onClickAppt: (a: Appointment) => void
  onClickSlot: (providerId: number, time: string) => void
}

function AppointmentGrid({ appointments, providers, patientMap, typeMap, onClickAppt, onClickSlot }: AppointmentGridProps) {
  const qc = useQueryClient()
  const bodyRef = useRef<HTMLDivElement>(null)
  const [slotH, setSlotH] = useState(14)

  // Drag-resize state
  const [drag, setDrag] = useState<{
    apptId: number
    startY: number
    origHeight: number
    origEndISO: string
    startISO: string
    deltaSlots: number
  } | null>(null)

  // Drag-move state
  const [blockDrag, setBlockDrag] = useState<{
    apptId: number
    origStartISO: string
    origEndISO: string
    origProviderId: number
    grabOffsetY: number
    previewProviderId: number
    previewStartISO: string
    previewEndISO: string
    hasMoved: boolean
    isConflict: boolean
  } | null>(null)

  const didDragRef = useRef(false)

  // Refs so the blockDrag effect doesn't need to re-register listeners on every data change
  const blockDragRef = useRef(blockDrag)
  useEffect(() => { blockDragRef.current = blockDrag }, [blockDrag])
  const appointmentsRef = useRef(appointments)
  useEffect(() => { appointmentsRef.current = appointments }, [appointments])
  const slotHRef = useRef(slotH)
  useEffect(() => { slotHRef.current = slotH }, [slotH])
  const providersRef = useRef(providers)
  useEffect(() => { providersRef.current = providers }, [providers])

  const resizeMutation = useMutation({
    mutationFn: ({ id, end_time }: { id: number; end_time: string }) =>
      api.updateAppointment(id, { end_time }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['appointments'] }),
  })

  const moveMutation = useMutation({
    mutationFn: ({ id, start_time, end_time, provider_id }: { id: number; start_time: string; end_time: string; provider_id: number }) =>
      api.updateAppointment(id, { start_time, end_time, provider_id }),
    onMutate: async ({ id, start_time, end_time, provider_id }) => {
      // Cancel any in-flight refetches so they don't overwrite our optimistic update
      await qc.cancelQueries({ queryKey: ['appointments'] })
      // Snapshot every matching cache entry so we can roll back on error
      const snapshots = qc.getQueriesData<{ data: { items: Appointment[] } }>({ queryKey: ['appointments'] })
      // Apply the optimistic update to all cached appointment lists
      qc.setQueriesData<{ data: { items: Appointment[] } }>({ queryKey: ['appointments'] }, old => {
        if (!old) return old
        return {
          ...old,
          data: {
            ...old.data,
            items: old.data.items.map(a =>
              a.id === id ? { ...a, start_time, end_time, provider_id } : a
            ),
          },
        }
      })
      return { snapshots }
    },
    onError: (_err, _vars, ctx) => {
      // Roll back all caches to their pre-mutation snapshots
      ctx?.snapshots.forEach(([key, data]) => qc.setQueryData(key, data))
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ['appointments'] }),
  })
  const moveMutationRef = useRef(moveMutation)
  useEffect(() => { moveMutationRef.current = moveMutation }, [moveMutation])

  // Measure available height
  useLayoutEffect(() => {
    const el = bodyRef.current
    if (!el) return
    const update = () => setSlotH(Math.max(10, el.clientHeight / SLOTS_TOTAL))
    update()
    const ro = new ResizeObserver(update)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // Global mouse handlers for drag
  useEffect(() => {
    if (!drag) return

    const onMove = (e: MouseEvent) => {
      const rawDelta = e.clientY - drag.startY
      const deltaSlots = Math.round(rawDelta / slotH)
      // Clamp: minimum 1 slot, maximum up to 5pm
      const start = new Date(drag.startISO)
      const origSlots = Math.round(drag.origHeight / slotH)
      const maxSlots = Math.floor((GRID_END_H * 60 - (start.getHours() * 60 + start.getMinutes())) / 10)
      const newSlots = Math.min(maxSlots, Math.max(1, origSlots + deltaSlots))
      setDrag(d => d ? { ...d, deltaSlots: newSlots - origSlots } : null)
    }

    const onUp = () => {
      if (!drag) return
      const start = new Date(drag.startISO)
      const origSlots = Math.round(drag.origHeight / slotH)
      const maxSlots = Math.floor((GRID_END_H * 60 - (start.getHours() * 60 + start.getMinutes())) / 10)
      const newSlots = Math.min(maxSlots, Math.max(1, origSlots + drag.deltaSlots))
      const newEnd = new Date(start.getTime() + newSlots * 10 * 60_000)
      const newEndISO = `${newEnd.getFullYear()}-${String(newEnd.getMonth()+1).padStart(2,'0')}-${String(newEnd.getDate()).padStart(2,'0')}T${String(newEnd.getHours()).padStart(2,'0')}:${String(newEnd.getMinutes()).padStart(2,'0')}:00`
      if (newEndISO !== drag.origEndISO) {
        resizeMutation.mutate({ id: drag.apptId, end_time: newEndISO })
      }
      didDragRef.current = true
      setDrag(null)
    }

    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [drag, slotH])

  // Global mouse handlers for block move drag — registered once, use refs for fresh values
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      const bd = blockDragRef.current
      const el = bodyRef.current
      if (!bd || !el) return
      const rect = el.getBoundingClientRect()
      const GUTTER = 56
      const pvs = providersRef.current
      const colWidth = (rect.width - GUTTER) / pvs.length
      const relX = e.clientX - rect.left - GUTTER
      const colIdx = Math.max(0, Math.min(pvs.length - 1, Math.floor(relX / colWidth)))
      const newProviderId = pvs[colIdx].id

      const sh = slotHRef.current
      const relY = (e.clientY - rect.top) + el.scrollTop - bd.grabOffsetY
      const rawSlot = Math.round(relY / sh)
      const durationMs = new Date(bd.origEndISO).getTime() - new Date(bd.origStartISO).getTime()
      const durationSlots = Math.round(durationMs / 60_000 / 10)
      const maxStartSlot = SLOTS_TOTAL - durationSlots
      const startSlot = Math.max(0, Math.min(maxStartSlot, rawSlot))

      const origStart = new Date(bd.origStartISO)
      const newStart = new Date(origStart)
      newStart.setHours(GRID_START_H, 0, 0, 0)
      newStart.setTime(newStart.getTime() + startSlot * 10 * 60_000)
      const newEnd = new Date(newStart.getTime() + durationMs)

      const toISO = (d: Date) =>
        `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}T${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}:00`

      const newStartMs = newStart.getTime()
      const newEndMs   = newEnd.getTime()
      const hasConflict = appointmentsRef.current.some(a =>
        a.id !== bd.apptId &&
        a.provider_id === newProviderId &&
        a.status !== 'cancelled' &&
        new Date(a.start_time).getTime() < newEndMs &&
        new Date(a.end_time).getTime()   > newStartMs
      )

      setBlockDrag(prev => prev ? {
        ...prev,
        previewProviderId: newProviderId,
        previewStartISO: toISO(newStart),
        previewEndISO: toISO(newEnd),
        hasMoved: true,
        isConflict: hasConflict,
      } : null)
    }

    const onUp = () => {
      const bd = blockDragRef.current
      if (!bd || !bd.hasMoved) { setBlockDrag(null); return }
      if (!bd.isConflict) {
        const changed =
          bd.previewStartISO !== bd.origStartISO ||
          bd.previewEndISO   !== bd.origEndISO   ||
          bd.previewProviderId !== bd.origProviderId
        if (changed) {
          moveMutationRef.current.mutate({
            id: bd.apptId,
            start_time: bd.previewStartISO,
            end_time: bd.previewEndISO,
            provider_id: bd.previewProviderId,
          })
        }
      }
      destroyTourIfActive()
      didDragRef.current = true
      setBlockDrag(null)
    }

    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const gridHeight = SLOTS_TOTAL * slotH

  // Time labels at each hour and half-hour
  const timeLabels: { top: number; label: string; isHour: boolean }[] = []
  for (let slot = 0; slot < SLOTS_TOTAL; slot++) {
    const totalMins = GRID_START_H * 60 + slot * 10
    const h = Math.floor(totalMins / 60)
    const m = totalMins % 60
    if (m === 0 || m === 30) {
      const hr = h > 12 ? h - 12 : h === 0 ? 12 : h
      const ampm = h >= 12 ? 'PM' : 'AM'
      timeLabels.push({
        top: slot * slotH,
        label: m === 0 ? `${hr} ${ampm}` : `${hr}:30`,
        isHour: m === 0,
      })
    }
  }

  return (
    <div data-tour="grid" className={`flex flex-col rounded-xl border border-surface-border overflow-hidden flex-1 min-h-0 ${(drag || blockDrag) ? 'select-none' : ''}`}>
      {/* Provider header row */}
      <div className="flex border-b border-surface-border bg-surface-card flex-shrink-0">
        <div className="w-14 flex-shrink-0 border-r border-surface-border" />
        {providers.map(p => (
          <div key={p.id} className="flex-1 min-w-[120px] border-r border-surface-border last:border-r-0 px-3 py-2 text-center">
            <p className="text-xs font-semibold text-slate-200">Dr. {p.last_name}</p>
            {p.specialty && <p className="text-[10px] text-slate-500 truncate">{p.specialty}</p>}
          </div>
        ))}
      </div>

      {/* Grid body — fills remaining height, scrollable */}
      <div ref={bodyRef} className="flex flex-1 min-h-0 overflow-y-auto">
        {/* Time gutter */}
        <div className="w-14 flex-shrink-0 border-r border-surface-border bg-surface-base relative" style={{ height: gridHeight }}>
          {timeLabels.map(({ top, label, isHour }) => (
            <div key={top} className="absolute right-2 select-none" style={{ top: top - 6 }}>
              <span className={`text-[10px] leading-none ${isHour ? 'text-slate-400 font-medium' : 'text-slate-600'}`}>
                {label}
              </span>
            </div>
          ))}
        </div>

        {/* One column per provider */}
        {providers.map(provider => {
          const provAppts = appointments.filter(a => a.provider_id === provider.id)
          const isFirstCol = provider.id === providers[0]?.id
          return (
            <div
              key={provider.id}
              {...(isFirstCol ? { 'data-tour': 'grid-column' } : {})}
              className="flex-1 min-w-[120px] relative border-r border-surface-border last:border-r-0 bg-surface-base cursor-cell"
              style={{ height: gridHeight }}
              onClick={e => {
                if (blockDrag?.hasMoved || didDragRef.current) return
                const el = bodyRef.current
                if (!el) return
                const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
                const relY = (e.clientY - rect.top) + el.scrollTop
                const rawSlot = Math.floor(relY / slotH)
                const slot = Math.max(0, Math.min(SLOTS_TOTAL - 1, rawSlot))
                const totalMin = GRID_START_H * 60 + slot * 10
                const hh = String(Math.floor(totalMin / 60)).padStart(2, '0')
                const mm = String(totalMin % 60).padStart(2, '0')
                onClickSlot(provider.id, `${hh}:${mm}`)
              }}
            >
              {/* Horizontal grid lines */}
              {Array.from({ length: SLOTS_TOTAL }, (_, i) => (
                <div
                  key={i}
                  className={`absolute inset-x-0 border-t pointer-events-none ${
                    i % 6 === 0 ? 'border-surface-border'
                    : i % 3 === 0 ? 'border-surface-border/50'
                    : 'border-surface-border/20'
                  }`}
                  style={{ top: i * slotH }}
                />
              ))}

              {/* Ghost preview block for block-move drag — rendered once per column */}
              {(() => {
                if (!blockDrag || blockDrag.previewProviderId !== provider.id) return null
                const movingAppt = appointments.find(a => a.id === blockDrag.apptId)
                const colorCls = movingAppt ? GRID_COLORS[movingAppt.status] : 'bg-accent/30 border-accent/50'
                return (
                  <div
                    className={`absolute inset-x-1 rounded border z-30 pointer-events-none ${
                      blockDrag.isConflict
                        ? 'bg-red-500/30 border-red-400/70'
                        : `${colorCls} opacity-60`
                    }`}
                    style={{
                      top: slotTop(blockDrag.previewStartISO, slotH) + 1,
                      height: slotHeight(blockDrag.previewStartISO, blockDrag.previewEndISO, slotH) - 2,
                    }}
                  />
                )
              })()}

              {/* Appointment blocks */}
              {provAppts.map((appt, apptIdx) => {
                const isResizing = drag?.apptId === appt.id
                const isMoving = blockDrag?.apptId === appt.id
                const isFirstAppt = isFirstCol && apptIdx === 0

                const top    = slotTop(appt.start_time, slotH)
                const baseH  = slotHeight(appt.start_time, appt.end_time, slotH)
                const height = isResizing
                  ? Math.max(slotH, baseH + drag.deltaSlots * slotH)
                  : baseH
                const patient  = patientMap.get(appt.patient_id)
                const typeName = typeMap.get(appt.appointment_type_id) ?? ''
                const colorCls = GRID_COLORS[appt.status]

                return (
                  <div key={appt.id}>

                    {/* Original block */}
                    <div
                      {...(isFirstAppt ? { 'data-tour': 'appt-block' } : {})}
                      onClick={e => {
                        e.stopPropagation()
                        if (didDragRef.current) { didDragRef.current = false; return }
                        onClickAppt(appt)
                      }}
                      onDragStart={e => e.preventDefault()}
                      onMouseDown={e => {
                        // Only start move drag on left button, not on resize handle
                        if (e.button !== 0) return
                        e.stopPropagation()
                        e.preventDefault()
                        const el = bodyRef.current
                        if (!el) return
                        const rect = el.getBoundingClientRect()
                        const grabOffsetY = (e.clientY - rect.top) + el.scrollTop - top
                        setBlockDrag({
                          apptId: appt.id,
                          origStartISO: appt.start_time,
                          origEndISO: appt.end_time,
                          origProviderId: appt.provider_id,
                          grabOffsetY,
                          previewProviderId: appt.provider_id,
                          previewStartISO: appt.start_time,
                          previewEndISO: appt.end_time,
                          hasMoved: false,
                          isConflict: false,
                        })
                      }}
                      title={`${patient ? `${patient.first_name} ${patient.last_name}` : `#${appt.patient_id}`} · ${typeName} · ${formatTime(appt.start_time)}`}
                      className={`absolute inset-x-1 rounded border overflow-hidden px-1.5 py-0.5 ${colorCls} ${
                        isMoving ? 'opacity-30 z-10' :
                        isResizing ? 'opacity-90 shadow-lg z-20' :
                        'cursor-grab hover:brightness-125 z-10'
                      } transition-shadow select-none`}
                      style={{ top: top + 1, height: height - 2 }}
                    >
                      {height <= slotH * 2 ? (
                        <p className="text-[10px] font-semibold leading-tight truncate">
                          {patient ? `${patient.first_name} ${patient.last_name}` : `#${appt.patient_id}`}
                          {typeName ? <span className="opacity-70"> · {typeName}</span> : null}
                        </p>
                      ) : (
                        <>
                          <p className="text-[11px] font-semibold leading-tight truncate">
                            {patient ? `${patient.first_name} ${patient.last_name}` : `#${appt.patient_id}`}
                          </p>
                          <p className="text-[10px] leading-tight opacity-80 truncate">{typeName}</p>
                          {height > slotH * 3 && (
                            <p className="text-[10px] leading-tight opacity-60">{formatTime(appt.start_time)}</p>
                          )}
                        </>
                      )}

                      {/* Resize handle */}
                      <div
                        title="Drag to resize"
                        onMouseDown={e => {
                          e.stopPropagation()
                          e.preventDefault()
                          setDrag({
                            apptId: appt.id,
                            startY: e.clientY,
                            origHeight: baseH,
                            origEndISO: appt.end_time,
                            startISO: appt.start_time,
                            deltaSlots: 0,
                          })
                        }}
                        {...(isFirstAppt ? { 'data-tour': 'resize-handle' } : {})}
                        className="absolute bottom-0 left-0 right-0 h-3 cursor-s-resize flex items-end justify-center pb-0.5 opacity-0 hover:opacity-100 transition-opacity"
                      >
                        <div className="w-6 h-1 rounded-full bg-current opacity-50" />
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ─── Week strip helpers ───────────────────────────────────────────────────────

function getWeekDays(anchor: string): string[] {
  // Returns 7 ISO date strings starting from Monday of the week containing anchor
  const d = new Date(`${anchor}T00:00`)
  const day = d.getDay() // 0=Sun
  const monday = new Date(d)
  monday.setDate(d.getDate() - ((day + 6) % 7))
  return Array.from({ length: 7 }, (_, i) => {
    const dd = new Date(monday)
    dd.setDate(monday.getDate() + i)
    return dd.toISOString().split('T')[0]
  })
}

// ─── Main view ────────────────────────────────────────────────────────────────

export function ScheduleView() {
  const today = todayISO()
  const qc = useQueryClient()
  const [showNewAppt, setShowNewAppt] = useState(false)
  const [newApptPrefill, setNewApptPrefill] = useState<{ time?: string; providerId?: number }>({})
  const [editAppt, setEditAppt] = useState<Appointment | null>(null)

  const [selectedDate, setSelectedDate] = useState<string | 'all'>(today)

  const weekDays = getWeekDays(today)

  const apptQuery   = useQuery({
    queryKey: ['appointments', selectedDate],
    queryFn: () => api.getAppointments({
      date: selectedDate === 'all' ? undefined : selectedDate,
      limit: 200,
    }),
  })
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

  const TOUR_KEY = 'dentalai_schedule_tour_done'
  const gridReady = !!(providerQuery.data?.data.items.length && apptQuery.data)
  const [showTourPrompt, setShowTourPrompt] = useState(false)

  useEffect(() => {
    if (!gridReady) return
    try { if (localStorage.getItem(TOUR_KEY)) return } catch {}

    // Wait until the welcome modal has been dismissed before showing the prompt
    const check = () => {
      try { return !!localStorage.getItem(WELCOME_DISMISSED_KEY) } catch { return true }
    }
    if (check()) {
      const t = setTimeout(() => setShowTourPrompt(true), 400)
      return () => clearTimeout(t)
    }
    const poll = setInterval(() => {
      if (check()) {
        clearInterval(poll)
        setTimeout(() => setShowTourPrompt(true), 400)
      }
    }, 300)
    return () => clearInterval(poll)
  }, [gridReady])

  const patientMap  = new Map((patientQuery.data?.data.items ?? []).map(p => [p.id, p]))
  const providerMap = new Map((providerQuery.data?.data.items ?? []).map(p => [p.id, p]))
  const typeMap     = new Map((typeQuery.data?.data.items ?? []).map(t => [t.id, t.name]))

  const appointments = [...(apptQuery.data?.data.items ?? [])].sort(
    (a, b) => new Date(a.start_time).getTime() - new Date(b.start_time).getTime()
  )

  const headingLabel = selectedDate === 'all'
    ? 'All Appointments'
    : selectedDate === today
    ? "Today's Schedule"
    : new Date(`${selectedDate}T00:00`).toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })

  return (
    <div className="flex flex-col h-full">
      {/* Sticky header */}
      <div className="sticky top-0 z-10 bg-surface-base border-b border-surface-border px-4 sm:px-6 pt-4 sm:pt-6 pb-3">
      {/* Header row */}
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="flex items-center gap-3 min-w-0">
          <CalendarDays className="h-6 w-6 text-accent flex-shrink-0" />
          <div className="min-w-0">
            <h1 className="text-lg font-semibold text-slate-100 truncate">{headingLabel}</h1>
            <p className="text-xs text-slate-400 hidden sm:block">
              {new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' })}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <button
            onClick={() => apptQuery.refetch()}
            className="flex items-center gap-1.5 rounded-lg border border-surface-border px-3 py-2 text-xs text-slate-400 hover:bg-surface-raised hover:text-slate-200 transition-colors"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${apptQuery.isFetching ? 'animate-spin' : ''}`} />
            <span className="hidden sm:inline">Refresh</span>
          </button>
          <span className="tour-glow-wrap hidden sm:inline-flex">
            <button
              onClick={() => startScheduleTour(() => { setShowNewAppt(false); setNewApptPrefill({}) })}
              className="flex items-center gap-1.5 rounded-lg bg-surface-card px-3 py-2 text-xs text-slate-400 hover:bg-surface-raised hover:text-slate-200 transition-colors"
              title="Take a tour"
            >
              <HelpCircle className="h-3.5 w-3.5" />
              <span>Tour</span>
            </button>
          </span>
          <Button size="sm" onClick={() => setShowNewAppt(true)} className="gap-1.5" data-tour="new-appt-btn">
            <Plus className="h-4 w-4" /> <span className="hidden sm:inline">New Appointment</span><span className="sm:hidden">New</span>
          </Button>
        </div>
      </div>

      {/* Week day strip */}
      <div className="flex items-center gap-1.5 overflow-x-auto pb-1">
        <button
          onClick={() => setSelectedDate('all')}
          className={`flex-shrink-0 rounded-lg border px-3 py-2 text-xs font-medium transition-colors ${
            selectedDate === 'all'
              ? 'border-accent bg-accent/20 text-accent'
              : 'border-surface-border text-slate-400 hover:bg-surface-raised hover:text-slate-200'
          }`}
        >
          All
        </button>
        {weekDays.map(day => {
          const d = new Date(`${day}T00:00`)
          const isToday = day === today
          const isSelected = selectedDate === day
          return (
            <button
              key={day}
              onClick={() => setSelectedDate(day)}
              className={`flex flex-shrink-0 flex-col items-center rounded-lg border px-3 py-2 text-xs transition-colors ${
                isSelected
                  ? 'border-accent bg-accent/20 text-accent'
                  : isToday
                  ? 'border-accent/40 text-slate-200 hover:bg-surface-raised'
                  : 'border-surface-border text-slate-400 hover:bg-surface-raised hover:text-slate-200'
              }`}
            >
              <span className="font-medium">{d.toLocaleDateString('en-US', { weekday: 'short' })}</span>
              <span className={`text-[11px] ${isToday ? 'font-bold' : ''}`}>{d.getDate()}</span>
              {isToday && <span className="mt-0.5 h-1 w-1 rounded-full bg-accent" />}
            </button>
          )
        })}
      </div>
      </div>{/* end sticky header */}

      {/* ── Mobile / "All" scrollable layout ── */}
      <div className={`flex-1 overflow-y-auto px-4 sm:px-6 py-4 sm:py-6 ${selectedDate !== 'all' ? 'md:hidden' : ''}`}>
        {/* Stats strip */}
        {!isLoading && !error && (
          <div className="mb-6 grid grid-cols-2 sm:grid-cols-4 gap-3">
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
            <p className="text-slate-400">No appointments {selectedDate === 'all' ? 'found' : selectedDate === today ? 'today' : 'on this day'}</p>
            <Button size="sm" className="mt-4 gap-1.5" onClick={() => setShowNewAppt(true)}>
              <Plus className="h-3.5 w-3.5" /> Book one now
            </Button>
          </div>
        )}

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
                  onClick={() => setEditAppt(appt)}
                  className="flex items-center gap-3 rounded-xl border border-surface-border bg-surface-card p-3 sm:p-4 hover:bg-surface-raised transition-colors cursor-pointer"
                >
                  <div className={`h-10 w-1 flex-shrink-0 rounded-full ${colors.dot}`} />
                  <div className="w-20 sm:w-24 flex-shrink-0">
                    <p className="text-sm font-semibold text-slate-200">{formatTime(appt.start_time)}</p>
                    <p className="flex items-center gap-1 text-xs text-slate-500">
                      <Clock className="h-3 w-3" />{formatTime(appt.end_time)}
                    </p>
                    {selectedDate === 'all' && (
                      <p className="text-[11px] text-slate-500 mt-0.5">
                        {new Date(appt.start_time).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                      </p>
                    )}
                  </div>
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
                  <div className="hidden w-36 flex-shrink-0 sm:block">
                    <p className="flex items-center gap-1.5 text-xs text-slate-400">
                      <Stethoscope className="h-3 w-3" />
                      {provider ? `Dr. ${provider.last_name}` : `#${appt.provider_id}`}
                    </p>
                  </div>
                  <div className="hidden w-36 flex-shrink-0 lg:block">
                    <NotesCell appt={appt} />
                  </div>
                  <button
                    disabled={isUpdating}
                    onClick={e => { e.stopPropagation(); statusMutation.mutate({ id: appt.id, status: NEXT_STATUS[appt.status] }) }}
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
      </div>

      {/* ── Desktop grid layout — fills remaining height, no scroll ── */}
      {selectedDate !== 'all' && (
        <div className="hidden md:flex md:flex-col flex-1 min-h-0 px-4 sm:px-6 pb-4 gap-3">
          {/* Compact stats row */}
          {!isLoading && !error && (
            <div className="flex gap-3 flex-shrink-0">
              {(['confirmed', 'completed', 'no_show', 'cancelled'] as AppointmentStatus[]).map(s => {
                const count = appointments.filter(a => a.status === s).length
                const colors = statusColors(s)
                return (
                  <div key={s} className="flex items-center gap-2 rounded-lg border border-surface-border bg-surface-card px-3 py-2">
                    <p className={`text-lg font-bold ${colors.text}`}>{count}</p>
                    <p className="text-xs text-slate-500 capitalize">{statusLabel(s)}</p>
                  </div>
                )
              })}
            </div>
          )}

          {isLoading && (
            <div className="flex-1 animate-pulse rounded-xl bg-surface-card border border-surface-border" />
          )}

          {error && (
            <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-400">
              Failed to load: {String(error)}
            </div>
          )}

          {!isLoading && !error && appointments.length === 0 && (
            <div className="flex flex-1 flex-col items-center justify-center rounded-xl border border-dashed border-surface-border text-center">
              <CalendarDays className="mb-3 h-10 w-10 text-slate-600" />
              <p className="text-slate-400">{selectedDate === today ? 'No appointments today' : 'No appointments on this day'}</p>
              <Button size="sm" className="mt-4 gap-1.5" onClick={() => setShowNewAppt(true)}>
                <Plus className="h-3.5 w-3.5" /> Book one now
              </Button>
            </div>
          )}

          {!isLoading && !error && appointments.length > 0 && (
            <AppointmentGrid
              appointments={appointments}
              providers={providerQuery.data?.data.items ?? []}
              patientMap={patientMap}
              typeMap={typeMap}
              onClickAppt={setEditAppt}
              onClickSlot={(providerId, time) => {
                setNewApptPrefill({ providerId, time })
                setShowNewAppt(true)
              }}
            />
          )}
        </div>
      )}

      {/* New appointment dialog */}
      <NewAppointmentDialog
        open={showNewAppt}
        onClose={() => { setShowNewAppt(false); setNewApptPrefill({}) }}
        patients={patientQuery.data?.data.items ?? []}
        providers={providerQuery.data?.data.items ?? []}
        appointmentTypes={typeQuery.data?.data.items ?? []}
        locations={(locationQuery.data?.data.items ?? []).map(l => ({ id: l.id, name: l.name }))}
        onCreated={() => qc.invalidateQueries({ queryKey: ['appointments'] })}
        initialDate={selectedDate !== 'all' ? selectedDate : todayISO()}
        initialTime={newApptPrefill.time}
        initialProviderId={newApptPrefill.providerId}
      />

      <EditAppointmentDialog
        appt={editAppt}
        onClose={() => setEditAppt(null)}
        providers={providerQuery.data?.data.items ?? []}
        appointmentTypes={typeQuery.data?.data.items ?? []}
        onSaved={() => qc.invalidateQueries({ queryKey: ['appointments'] })}
      />

      {/* Tour welcome prompt — desktop only */}
      {showTourPrompt && (
        <div className="hidden sm:flex fixed bottom-6 right-6 z-50 w-72 rounded-2xl border border-surface-border bg-surface-card shadow-2xl p-5 flex-col gap-3 animate-fade-in">
          <div className="flex items-start gap-3">
            <span className="text-2xl leading-none">👋</span>
            <div>
              <p className="text-sm font-semibold text-slate-100">New to the calendar?</p>
              <p className="text-xs text-slate-400 mt-0.5 leading-relaxed">Take a quick tour to see how to drag, resize, and book appointments.</p>
            </div>
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => {
                setShowTourPrompt(false)
                try { localStorage.setItem(TOUR_KEY, '1') } catch {}
                setTimeout(() => startScheduleTour(() => { setShowNewAppt(false); setNewApptPrefill({}) }), 100)
              }}
              className="flex-1 rounded-lg bg-accent px-3 py-2 text-xs font-medium text-white hover:bg-accent/90 transition-colors"
            >
              Take the tour
            </button>
            <button
              onClick={() => {
                setShowTourPrompt(false)
                try { localStorage.setItem(TOUR_KEY, '1') } catch {}
              }}
              className="rounded-lg border border-surface-border px-3 py-2 text-xs text-slate-400 hover:text-slate-200 transition-colors"
            >
              Skip
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
