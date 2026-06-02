/**
 * Recall Queue View — overdue recalls with full status management.
 *
 * Actions (no API key needed):
 *   Mark Contacted  — sets status = "contacted", stamps last_contacted_at
 *   Schedule        — sets status = "scheduled"
 *   Dismiss         — sets status = "dismissed"
 *   Draft Message   — calls AI agent (needs OPENAI_API_KEY)
 *
 * Status filter tabs let you switch between pending / contacted / scheduled / dismissed.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Bell, Copy, Check, RefreshCw, Bot, Phone, CalendarCheck, XCircle } from 'lucide-react'
import { api, type Patient, type PatientRecall, type RecallStatus } from '@/lib/api'
import { daysOverdue, formatDateShort, todayISO } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'

interface RecallRow {
  recall: PatientRecall
  patient: Patient | undefined
  daysOver: number
}

const STATUS_TABS: { value: RecallStatus | 'all'; label: string }[] = [
  { value: 'pending',    label: 'Pending' },
  { value: 'contacted',  label: 'Contacted' },
  { value: 'scheduled',  label: 'Scheduled' },
  { value: 'dismissed',  label: 'Dismissed' },
]

export function RecallQueueView() {
  const today = todayISO()
  const qc = useQueryClient()
  const [tab, setTab] = useState<RecallStatus>('pending')
  const [sessionId] = useState(() => `recall-${Date.now()}`)
  const [copied, setCopied] = useState(false)
  const [modal, setModal] = useState({ open: false, patientName: '', message: '', isLoading: false, error: '' })

  // Fetch recalls for the active tab
  const recallQuery = useQuery({
    queryKey: ['recalls', tab, today],
    queryFn: () => api.getRecalls({
      status: tab,
      due_before: tab === 'pending' ? today : undefined,
      limit: 200,
    }),
  })

  const patientQuery = useQuery({
    queryKey: ['patients'],
    queryFn: () => api.getPatients({ limit: 200 }),
  })

  const statusMutation = useMutation({
    mutationFn: ({ id, status }: { id: number; status: RecallStatus }) =>
      api.updateRecall(id, { status }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['recalls'] }),
  })

  const patientMap = new Map<number, Patient>(
    (patientQuery.data?.data.items ?? []).map(p => [p.id, p])
  )

  const rows: RecallRow[] = (recallQuery.data?.data.items ?? [])
    .map(recall => ({
      recall,
      patient: patientMap.get(recall.patient_id),
      daysOver: daysOverdue(recall.due_date),
    }))
    .sort((a, b) => b.daysOver - a.daysOver)

  async function handleDraft(row: RecallRow) {
    const name = row.patient
      ? `${row.patient.first_name} ${row.patient.last_name}`
      : `Patient #${row.recall.patient_id}`

    setModal({ open: true, patientName: name, message: '', isLoading: true, error: '' })
    try {
      const result = await api.agentChat(
        `Draft a recall message for patient ${row.recall.patient_id}`,
        sessionId
      )
      setModal(p => ({ ...p, isLoading: false, message: result.response }))
    } catch (err) {
      setModal(p => ({ ...p, isLoading: false, error: String(err) }))
    }
  }

  async function handleCopy() {
    await navigator.clipboard.writeText(modal.message)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  function markStatus(id: number, status: RecallStatus) {
    statusMutation.mutate({ id, status })
  }

  const isLoading = recallQuery.isLoading || patientQuery.isLoading

  function urgencyLabel(days: number) {
    if (days > 90) return <span className="text-xs font-semibold text-red-400">{days}d overdue</span>
    if (days > 30) return <span className="text-xs font-semibold text-amber-400">{days}d overdue</span>
    if (days > 0)  return <span className="text-xs font-semibold text-yellow-400">{days}d overdue</span>
    return <span className="text-xs text-slate-400">due {formatDateShort(rows[0]?.recall.due_date ?? '')}</span>
  }

  return (
    <div className="p-6">
      {/* Header */}
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Bell className="h-6 w-6 text-accent" />
          <div>
            <h1 className="text-xl font-semibold text-slate-100">Recall Queue</h1>
            <p className="text-sm text-slate-400">{rows.length} patient{rows.length !== 1 ? 's' : ''} · {tab}</p>
          </div>
        </div>
        <button
          onClick={() => recallQuery.refetch()}
          className="flex items-center gap-1.5 rounded-lg border border-surface-border px-3 py-2 text-xs text-slate-400 hover:bg-surface-raised hover:text-slate-200 transition-colors"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${recallQuery.isFetching ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {/* Status tabs */}
      <div className="mb-5 flex gap-1 rounded-lg border border-surface-border bg-surface-card p-1 w-fit">
        {STATUS_TABS.map(t => (
          <button
            key={t.value}
            onClick={() => setTab(t.value as RecallStatus)}
            className={`rounded-md px-4 py-1.5 text-sm font-medium transition-colors ${
              tab === t.value
                ? 'bg-accent text-white'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {isLoading && (
        <div className="space-y-2">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="h-16 animate-pulse rounded-xl bg-surface-card border border-surface-border" />
          ))}
        </div>
      )}

      {recallQuery.error && (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-400">
          {String(recallQuery.error)}
        </div>
      )}

      {!isLoading && rows.length === 0 && !recallQuery.error && (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-surface-border py-16 text-center">
          <Bell className="mb-3 h-10 w-10 text-slate-600" />
          <p className="text-slate-400">
            {tab === 'pending' ? 'No overdue recalls — great work!' : `No ${tab} recalls.`}
          </p>
        </div>
      )}

      {!isLoading && rows.length > 0 && (
        <div className="rounded-xl border border-surface-border overflow-hidden">
          {/* Table header */}
          <div className="grid grid-cols-[1fr_150px_110px_130px_auto] gap-4 border-b border-surface-border bg-surface-raised px-5 py-3">
            {['Patient', 'Recall Type', 'Due Date', 'Overdue', 'Actions'].map(col => (
              <p key={col} className="text-xs font-medium uppercase tracking-wide text-slate-500">{col}</p>
            ))}
          </div>

          <div className="divide-y divide-surface-border">
            {rows.map(row => {
              const isUpdating = statusMutation.isPending && statusMutation.variables?.id === row.recall.id
              return (
                <div
                  key={row.recall.id}
                  className="grid grid-cols-[1fr_150px_110px_130px_auto] items-center gap-4 bg-surface-card px-5 py-3.5 hover:bg-surface-raised transition-colors"
                >
                  {/* Patient */}
                  <div>
                    <p className="text-sm font-medium text-slate-200">
                      {row.patient
                        ? `${row.patient.first_name} ${row.patient.last_name}`
                        : `Patient #${row.recall.patient_id}`}
                    </p>
                    {row.recall.last_contacted_at && (
                      <p className="text-xs text-slate-500">
                        Last contacted {formatDateShort(row.recall.last_contacted_at.slice(0, 10))}
                      </p>
                    )}
                  </div>

                  {/* Recall type */}
                  <p className="text-sm text-slate-400 capitalize truncate">{row.recall.recall_type}</p>

                  {/* Due date */}
                  <p className="text-sm text-slate-400">{formatDateShort(row.recall.due_date)}</p>

                  {/* Overdue */}
                  {urgencyLabel(row.daysOver)}

                  {/* Actions */}
                  <div className="flex items-center gap-1.5">
                    {tab === 'pending' && (
                      <>
                        <button
                          disabled={isUpdating}
                          onClick={() => markStatus(row.recall.id, 'contacted')}
                          title="Mark as contacted"
                          className="rounded-md p-1.5 text-blue-400 hover:bg-blue-500/15 transition-colors disabled:opacity-40"
                        >
                          <Phone className="h-3.5 w-3.5" />
                        </button>
                        <button
                          disabled={isUpdating}
                          onClick={() => markStatus(row.recall.id, 'scheduled')}
                          title="Mark as scheduled"
                          className="rounded-md p-1.5 text-green-400 hover:bg-green-500/15 transition-colors disabled:opacity-40"
                        >
                          <CalendarCheck className="h-3.5 w-3.5" />
                        </button>
                        <button
                          disabled={isUpdating}
                          onClick={() => markStatus(row.recall.id, 'dismissed')}
                          title="Dismiss"
                          className="rounded-md p-1.5 text-slate-500 hover:bg-slate-500/15 transition-colors disabled:opacity-40"
                        >
                          <XCircle className="h-3.5 w-3.5" />
                        </button>
                        <button
                          onClick={() => handleDraft(row)}
                          title="Draft AI recall message"
                          className="rounded-md p-1.5 text-accent hover:bg-accent/15 transition-colors"
                        >
                          <Bot className="h-3.5 w-3.5" />
                        </button>
                      </>
                    )}
                    {tab === 'contacted' && (
                      <>
                        <button disabled={isUpdating} onClick={() => markStatus(row.recall.id, 'scheduled')} title="Mark scheduled" className="rounded-md p-1.5 text-green-400 hover:bg-green-500/15 transition-colors disabled:opacity-40"><CalendarCheck className="h-3.5 w-3.5" /></button>
                        <button disabled={isUpdating} onClick={() => markStatus(row.recall.id, 'pending')} title="Move back to pending" className="rounded-md p-1.5 text-slate-400 hover:bg-slate-500/15 transition-colors disabled:opacity-40"><Bell className="h-3.5 w-3.5" /></button>
                      </>
                    )}
                    {(tab === 'scheduled' || tab === 'dismissed') && (
                      <button disabled={isUpdating} onClick={() => markStatus(row.recall.id, 'pending')} title="Re-open" className="rounded-md p-1.5 text-slate-400 hover:bg-slate-500/15 transition-colors text-xs disabled:opacity-40">Re-open</button>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Draft message modal */}
      <Dialog open={modal.open} onOpenChange={open => setModal(p => ({ ...p, open }))}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Recall Message — {modal.patientName}</DialogTitle>
            <DialogDescription>AI-drafted outreach. Edit before sending.</DialogDescription>
          </DialogHeader>

          {modal.isLoading && (
            <div className="flex items-center gap-3 py-8 text-slate-400">
              <div className="h-5 w-5 animate-spin rounded-full border-2 border-accent border-t-transparent" />
              <span className="text-sm">Drafting…</span>
            </div>
          )}
          {modal.error && (
            <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">{modal.error}</div>
          )}
          {!modal.isLoading && modal.message && (
            <>
              <pre className="whitespace-pre-wrap rounded-lg border border-surface-border bg-surface-raised p-4 text-sm text-slate-300 font-sans leading-relaxed">
                {modal.message}
              </pre>
              <div className="flex justify-end pt-2">
                <Button variant="secondary" size="sm" onClick={handleCopy} className="gap-2">
                  {copied ? <><Check className="h-3.5 w-3.5 text-green-400" />Copied</> : <><Copy className="h-3.5 w-3.5" />Copy</>}
                </Button>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
