import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Users, Plus, Search, RefreshCw, X, HelpCircle, Calendar, Bell, ChevronRight, ExternalLink } from 'lucide-react'
import { api, type Patient } from '@/lib/api'
import { formatDateShort } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { startPatientsTour, destroyPatientsTourIfActive } from '@/hooks/usePatientsTour'
import { WELCOME_DISMISSED_KEY } from '@/components/WelcomeModal'

const PATIENTS_TOUR_KEY = 'dentalai_patients_tour_done'

const STATUS_COLORS: Record<string, string> = {
  confirmed: 'text-blue-400',
  completed: 'text-green-400',
  pending:   'text-yellow-400',
  no_show:   'text-red-400',
  cancelled: 'text-slate-500',
}

const RECALL_COLORS: Record<string, string> = {
  pending:   'text-amber-400',
  contacted: 'text-blue-400',
  scheduled: 'text-green-400',
  dismissed: 'text-slate-500',
}

// ─── Add Patient Dialog ──────────────────────────────────────────────────────

interface AddPatientDialogProps {
  open: boolean
  onClose: () => void
  onCreated: () => void
}

function AddPatientDialog({ open, onClose, onCreated }: AddPatientDialogProps) {
  const [form, setForm] = useState({ first_name: '', last_name: '', dob: '', email: '', phone: '' })
  const [error, setError] = useState('')

  const mutation = useMutation({
    mutationFn: () =>
      api.createPatient({
        first_name: form.first_name.trim(),
        last_name: form.last_name.trim(),
        dob: form.dob || undefined,
        email: form.email.trim() || undefined,
        phone: form.phone.trim() || undefined,
      }),
    onSuccess: () => {
      onCreated()
      onClose()
      setForm({ first_name: '', last_name: '', dob: '', email: '', phone: '' })
      setError('')
    },
    onError: (e: Error) => setError(e.message),
  })

  function field(label: string, key: keyof typeof form, type = 'text', required = false) {
    return (
      <div>
        <label className="mb-1 block text-xs font-medium text-slate-400">
          {label}{required && <span className="text-red-400 ml-0.5">*</span>}
        </label>
        <Input
          type={type}
          value={form[key]}
          onChange={e => setForm(f => ({ ...f, [key]: e.target.value }))}
          className="h-9 text-sm"
        />
      </div>
    )
  }

  return (
    <Dialog open={open} onOpenChange={v => { if (!v) onClose() }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add Patient</DialogTitle>
          <DialogDescription>Enter the new patient's details.</DialogDescription>
        </DialogHeader>
        <div className="space-y-3 pt-1">
          <div className="grid grid-cols-2 gap-3">
            {field('First Name', 'first_name', 'text', true)}
            {field('Last Name', 'last_name', 'text', true)}
          </div>
          {field('Date of Birth', 'dob', 'date')}
          {field('Email', 'email', 'email')}
          {field('Phone', 'phone', 'tel')}
          {error && <p className="text-xs text-red-400">{error}</p>}
          <div className="flex justify-end gap-2 pt-1">
            <Button variant="secondary" size="sm" onClick={onClose}>Cancel</Button>
            <Button
              size="sm"
              disabled={!form.first_name.trim() || !form.last_name.trim() || mutation.isPending}
              onClick={() => mutation.mutate()}
            >
              {mutation.isPending ? 'Saving…' : 'Add Patient'}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

// ─── Patient Detail Panel ────────────────────────────────────────────────────

interface PatientPanelProps {
  patient: Patient
  onClose: () => void
  onBook: (patient: Patient) => void
}

function PatientPanel({ patient, onClose, onBook }: PatientPanelProps) {
  const apptQuery = useQuery({
    queryKey: ['appointments', 'patient', patient.id],
    queryFn: () => api.getAppointments({ patient_id: patient.id, limit: 10 }),
  })

  const recallQuery = useQuery({
    queryKey: ['recalls', 'patient', patient.id],
    queryFn: () => api.getRecalls({ patient_id: patient.id, limit: 5 }),
  })

  const typeQuery = useQuery({ queryKey: ['appointment_types'], queryFn: () => api.getAppointmentTypes() })
  const providerQuery = useQuery({ queryKey: ['providers'], queryFn: () => api.getProviders() })

  const typeMap = new Map((typeQuery.data?.data.items ?? []).map(t => [t.id, t.name]))
  const providerMap = new Map((providerQuery.data?.data.items ?? []).map(p => [p.id, `Dr. ${p.last_name}`]))

  const appts = [...(apptQuery.data?.data.items ?? [])]
    .sort((a, b) => new Date(b.start_time).getTime() - new Date(a.start_time).getTime())
    .slice(0, 6)

  const recalls = recallQuery.data?.data.items ?? []
  const activeRecall = recalls.find(r => r.status === 'pending' || r.status === 'contacted')

  return (
    <div className="flex flex-col h-full border-l border-surface-border bg-surface-card w-full sm:w-80 xl:w-96 flex-shrink-0">
      {/* Panel header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-surface-border">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-slate-100 truncate">{patient.first_name} {patient.last_name}</p>
          <p className="text-xs text-slate-500">{patient.dob ? `DOB ${new Date(`${patient.dob}T00:00`).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}` : 'No DOB on file'}</p>
        </div>
        <button onClick={onClose} className="text-red-500 hover:text-red-400 transition-colors flex-shrink-0 ml-2">
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-5">
        {/* Contact info */}
        <div className="space-y-1.5">
          {patient.email && <p className="text-xs text-slate-400 truncate">{patient.email}</p>}
          {patient.phone && <p className="text-xs text-slate-400">{patient.phone}</p>}
          {!patient.email && !patient.phone && <p className="text-xs text-slate-600">No contact info on file</p>}
        </div>

        {/* Recall status */}
        {recalls.length > 0 && (
          <div>
            <p className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-2 flex items-center gap-1.5">
              <Bell className="h-3 w-3" /> Recall
            </p>
            {activeRecall ? (
              <div className="rounded-lg border border-surface-border bg-surface-base px-3 py-2">
                <p className="text-xs text-slate-300 capitalize">{activeRecall.recall_type}</p>
                <p className={`text-xs mt-0.5 ${RECALL_COLORS[activeRecall.status]}`}>
                  {activeRecall.status} · due {formatDateShort(activeRecall.due_date)}
                </p>
              </div>
            ) : (
              <p className="text-xs text-green-400">No active recalls</p>
            )}
          </div>
        )}

        {/* Appointment history */}
        <div>
          <p className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-2 flex items-center gap-1.5">
            <Calendar className="h-3 w-3" /> Appointment History
          </p>
          {apptQuery.isLoading && (
            <div className="space-y-1.5">
              {[...Array(3)].map((_, i) => <div key={i} className="h-10 animate-pulse rounded-lg bg-surface-base" />)}
            </div>
          )}
          {!apptQuery.isLoading && appts.length === 0 && (
            <p className="text-xs text-slate-600">No appointments on record</p>
          )}
          {appts.map(appt => (
            <div key={appt.id} className="flex items-center justify-between rounded-lg border border-surface-border bg-surface-base px-3 py-2 mb-1.5">
              <div className="min-w-0">
                <p className="text-xs text-slate-300 truncate capitalize">{typeMap.get(appt.appointment_type_id) ?? 'Appointment'}</p>
                <p className="text-xs text-slate-500">{providerMap.get(appt.provider_id) ?? '—'} · {new Date(appt.start_time).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}</p>
              </div>
              <span className={`text-xs font-medium capitalize flex-shrink-0 ml-2 ${STATUS_COLORS[appt.status] ?? 'text-slate-400'}`}>
                {appt.status}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Book button */}
      <div className="p-4 border-t border-surface-border">
        <Button size="sm" className="w-full gap-2" onClick={() => onBook(patient)}>
          <ExternalLink className="h-3.5 w-3.5" />
          Book Appointment
        </Button>
      </div>
    </div>
  )
}

// ─── Main View ───────────────────────────────────────────────────────────────

export function PatientsView() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const [showAdd, setShowAdd] = useState(false)
  const [selectedPatient, setSelectedPatient] = useState<Patient | null>(null)
  const [showTourPrompt, setShowTourPrompt] = useState(false)

  useEffect(() => {
    try { if (localStorage.getItem(PATIENTS_TOUR_KEY)) return } catch {}
    const poll = setInterval(() => {
      try {
        if (localStorage.getItem(WELCOME_DISMISSED_KEY)) {
          clearInterval(poll)
          setShowTourPrompt(true)
        }
      } catch { clearInterval(poll) }
    }, 300)
    return () => clearInterval(poll)
  }, [])

  const query = useQuery({
    queryKey: ['patients', search],
    queryFn: () => api.getPatients({ name: search || undefined, limit: 100 }),
  })

  const patients = query.data?.data.items ?? []

  // Close panel if selected patient disappears from search results
  useEffect(() => {
    if (selectedPatient && patients.length > 0 && !patients.find(p => p.id === selectedPatient.id)) {
      setSelectedPatient(null)
    }
  }, [patients, selectedPatient])

  function handleBook(_patient: Patient) {
    navigate('/')
  }

  return (
    <div className="flex flex-col h-full">
      {/* Sticky header */}
      <div className="sticky top-0 z-10 bg-surface-base border-b border-surface-border px-4 sm:px-6 pt-4 sm:pt-6 pb-3">
        <div className="mb-3 flex items-center justify-between gap-2">
          <div className="flex items-center gap-3 min-w-0">
            <Users className="h-6 w-6 text-accent flex-shrink-0" />
            <div className="min-w-0">
              <h1 className="text-lg font-semibold text-slate-100">Patients</h1>
              <p className="text-xs text-slate-400 hidden sm:block">{patients.length} record{patients.length !== 1 ? 's' : ''}</p>
            </div>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            <span className="tour-glow-wrap hidden sm:inline-flex">
              <button
                onClick={() => startPatientsTour()}
                className="flex items-center gap-1.5 rounded-lg bg-surface-card px-3 py-2 text-xs text-slate-400 hover:bg-surface-raised hover:text-slate-200 transition-colors"
                title="Take a tour"
              >
                <HelpCircle className="h-3.5 w-3.5" />
                <span>Tour</span>
              </button>
            </span>
            <button
              onClick={() => qc.invalidateQueries({ queryKey: ['patients'] })}
              className="flex items-center gap-1.5 rounded-lg border border-surface-border px-3 py-2 text-xs text-slate-400 hover:bg-surface-raised hover:text-slate-200 transition-colors"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${query.isFetching ? 'animate-spin' : ''}`} />
              <span className="hidden sm:inline">Refresh</span>
            </button>
            <Button data-tour="patients-add" size="sm" onClick={() => { destroyPatientsTourIfActive(); setShowAdd(true) }} className="gap-1.5">
              <Plus className="h-4 w-4" />
              <span className="hidden sm:inline">Add Patient</span>
              <span className="sm:hidden">Add</span>
            </Button>
          </div>
        </div>

        {/* Search bar */}
        <div data-tour="patients-search" className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-500" />
          <Input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search by name…"
            className="pl-9 h-9 text-sm"
          />
          {search && (
            <button onClick={() => setSearch('')} className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300">
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* Body: table + optional slide-over panel */}
      <div className="flex flex-1 min-h-0">
        {/* Scrollable list */}
        <div className="flex-1 overflow-y-auto px-4 sm:px-6 py-4">
          {query.isLoading && (
            <div className="space-y-2">
              {[...Array(8)].map((_, i) => (
                <div key={i} className="h-14 animate-pulse rounded-xl bg-surface-card border border-surface-border" />
              ))}
            </div>
          )}

          {query.error && (
            <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-400">
              {String(query.error)}
            </div>
          )}

          {!query.isLoading && patients.length === 0 && (
            <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-surface-border py-16 text-center">
              <Users className="mb-3 h-10 w-10 text-slate-600" />
              <p className="text-slate-400">{search ? `No patients matching "${search}"` : 'No patients yet.'}</p>
            </div>
          )}

          {patients.length > 0 && (
            <>
              {/* Desktop table */}
              <div data-tour="patients-table" className="hidden sm:block rounded-xl border border-surface-border overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-surface-raised border-b border-surface-border">
                    <tr>
                      {['Name', 'Date of Birth', 'Email', 'Phone', ''].map(h => (
                        <th key={h} className="px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wide">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-surface-border">
                    {patients.map(p => (
                      <tr
                        key={p.id}
                        onClick={() => setSelectedPatient(prev => prev?.id === p.id ? null : p)}
                        className={`cursor-pointer transition-colors ${selectedPatient?.id === p.id ? 'bg-accent/10' : 'hover:bg-surface-raised/50'}`}
                      >
                        <td className="px-4 py-3 font-medium text-slate-200">{p.first_name} {p.last_name}</td>
                        <td className="px-4 py-3 text-slate-400">{p.dob ? new Date(`${p.dob}T00:00`).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) : '—'}</td>
                        <td className="px-4 py-3 text-slate-400">{p.email ?? '—'}</td>
                        <td className="px-4 py-3 text-slate-400">{p.phone ?? '—'}</td>
                        <td className="px-4 py-3 text-slate-500">
                          <ChevronRight className={`h-4 w-4 transition-transform ${selectedPatient?.id === p.id ? 'rotate-90 text-accent' : ''}`} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Mobile cards */}
              <div className="sm:hidden space-y-2">
                {patients.map(p => (
                  <div
                    key={p.id}
                    onClick={() => setSelectedPatient(prev => prev?.id === p.id ? null : p)}
                    className={`rounded-xl border border-surface-border bg-surface-card p-4 cursor-pointer transition-colors ${selectedPatient?.id === p.id ? 'border-accent/40 bg-accent/5' : ''}`}
                  >
                    <div className="flex items-center justify-between">
                      <p className="font-medium text-slate-200 mb-1">{p.first_name} {p.last_name}</p>
                      <ChevronRight className={`h-4 w-4 text-slate-500 transition-transform ${selectedPatient?.id === p.id ? 'rotate-90 text-accent' : ''}`} />
                    </div>
                    <p className="text-xs text-slate-500">{p.dob ? new Date(`${p.dob}T00:00`).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) : 'No DOB'}</p>
                    {p.email && <p className="text-xs text-slate-500 mt-0.5">{p.email}</p>}
                    {p.phone && <p className="text-xs text-slate-500 mt-0.5">{p.phone}</p>}
                    {/* Inline panel on mobile */}
                    {selectedPatient?.id === p.id && (
                      <div className="mt-3 pt-3 border-t border-surface-border">
                        <PatientPanel patient={p} onClose={() => setSelectedPatient(null)} onBook={handleBook} />
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </>
          )}
        </div>

        {/* Desktop slide-over panel */}
        {selectedPatient && (
          <div className="hidden sm:flex">
            <PatientPanel patient={selectedPatient} onClose={() => setSelectedPatient(null)} onBook={handleBook} />
          </div>
        )}
      </div>

      {/* First-time tour prompt */}
      {showTourPrompt && (
        <div className="hidden sm:flex fixed bottom-6 right-6 z-50 w-72 flex-col gap-3 rounded-2xl border border-surface-border bg-surface-card p-4 shadow-2xl">
          <div className="flex items-start justify-between gap-2">
            <p className="text-sm font-medium text-slate-100">👋 Exploring patients?</p>
            <button onClick={() => { try { localStorage.setItem(PATIENTS_TOUR_KEY, '1') } catch {} setShowTourPrompt(false) }} className="text-red-500 hover:text-red-400 transition-colors text-lg leading-none">×</button>
          </div>
          <p className="text-xs text-slate-400 leading-relaxed">Click any patient row to see their appointment history and recall status, or take the quick tour.</p>
          <div className="flex gap-2">
            <button
              onClick={() => {
                try { localStorage.setItem(PATIENTS_TOUR_KEY, '1') } catch {}
                setShowTourPrompt(false)
                setTimeout(startPatientsTour, 100)
              }}
              className="flex-1 rounded-lg bg-accent px-3 py-2 text-xs font-medium text-white hover:bg-accent/90 transition-colors"
            >
              Take the tour
            </button>
            <button onClick={() => { try { localStorage.setItem(PATIENTS_TOUR_KEY, '1') } catch {} setShowTourPrompt(false) }} className="rounded-lg border border-surface-border px-3 py-2 text-xs text-slate-400 hover:bg-surface-raised transition-colors">
              Skip
            </button>
          </div>
        </div>
      )}

      <AddPatientDialog
        open={showAdd}
        onClose={() => setShowAdd(false)}
        onCreated={() => qc.invalidateQueries({ queryKey: ['patients'] })}
      />
    </div>
  )
}
