import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Users, Plus, Search, RefreshCw, X } from 'lucide-react'
import { api } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'

// ─── Add Patient Dialog ────────────────────────────────────────────────────

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

// ─── Main View ─────────────────────────────────────────────────────────────

export function PatientsView() {
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const [showAdd, setShowAdd] = useState(false)

  const query = useQuery({
    queryKey: ['patients', search],
    queryFn: () => api.getPatients({ name: search || undefined, limit: 100 }),
  })

  const patients = query.data?.data.items ?? []

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
            <button
              onClick={() => qc.invalidateQueries({ queryKey: ['patients'] })}
              className="flex items-center gap-1.5 rounded-lg border border-surface-border px-3 py-2 text-xs text-slate-400 hover:bg-surface-raised hover:text-slate-200 transition-colors"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${query.isFetching ? 'animate-spin' : ''}`} />
              <span className="hidden sm:inline">Refresh</span>
            </button>
            <Button size="sm" onClick={() => setShowAdd(true)} className="gap-1.5">
              <Plus className="h-4 w-4" />
              <span className="hidden sm:inline">Add Patient</span>
              <span className="sm:hidden">Add</span>
            </Button>
          </div>
        </div>

        {/* Search bar */}
        <div className="relative">
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

      {/* Scrollable content */}
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

        {/* Desktop table */}
        {patients.length > 0 && (
          <>
            <div className="hidden sm:block rounded-xl border border-surface-border overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-surface-raised border-b border-surface-border">
                  <tr>
                    {['Name', 'Date of Birth', 'Email', 'Phone'].map(h => (
                      <th key={h} className="px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wide">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-surface-border">
                  {patients.map(p => (
                    <tr key={p.id} className="hover:bg-surface-raised/50 transition-colors">
                      <td className="px-4 py-3 font-medium text-slate-200">{p.first_name} {p.last_name}</td>
                      <td className="px-4 py-3 text-slate-400">{p.dob ? new Date(`${p.dob}T00:00`).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) : '—'}</td>
                      <td className="px-4 py-3 text-slate-400">{p.email ?? '—'}</td>
                      <td className="px-4 py-3 text-slate-400">{p.phone ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Mobile cards */}
            <div className="sm:hidden space-y-2">
              {patients.map(p => (
                <div key={p.id} className="rounded-xl border border-surface-border bg-surface-card p-4">
                  <p className="font-medium text-slate-200 mb-1">{p.first_name} {p.last_name}</p>
                  <p className="text-xs text-slate-500">{p.dob ? new Date(`${p.dob}T00:00`).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) : 'No DOB'}</p>
                  {p.email && <p className="text-xs text-slate-500 mt-0.5">{p.email}</p>}
                  {p.phone && <p className="text-xs text-slate-500 mt-0.5">{p.phone}</p>}
                </div>
              ))}
            </div>
          </>
        )}
      </div>

      <AddPatientDialog
        open={showAdd}
        onClose={() => setShowAdd(false)}
        onCreated={() => qc.invalidateQueries({ queryKey: ['patients'] })}
      />
    </div>
  )
}
