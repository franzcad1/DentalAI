/**
 * Ops View: read-only monitoring page (M1b). Not linked in the sidebar; open /ops.
 *
 * Reads GET /api/v1/ops/summary with the X-Ops-Token header. The token is typed
 * in by the operator and kept only in sessionStorage for this tab. The data is
 * in-memory on the backend, so it resets on restart or redeploy; the page says so.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'

const BASE_URL: string = (import.meta.env.VITE_API_URL as string) || 'http://localhost:8000'

interface RouteStats { count: number; p50: number | null; p95: number | null }
interface OpsSummary {
  window_seconds: number
  since_start_seconds: number
  note: string
  http: {
    requests_by_status_class: Record<string, number>
    latency_ms_by_route: Record<string, RouteStats>
  }
  agent: {
    turns: Record<string, number>
    llm_call_p95_ms: number | null
    groq_429: number
    tool_parse_errors: number
    tokens: Record<string, number>
    tool_calls: Record<string, number>
  }
  rag: Record<string, number>
  scheduler: Record<string, number>
  recent_errors: { at: number; request_id: string; route: string; status: number; error_type: string }[]
  active_alerts: string[]
  health: { status: string; checks: Record<string, string> }
}

async function fetchSummary(token: string): Promise<OpsSummary> {
  const res = await fetch(`${BASE_URL}/api/v1/ops/summary?window_s=900`, {
    headers: { 'X-Ops-Token': token },
  })
  if (res.status === 404) throw new Error('Ops endpoint is off (OPS_TOKEN is not set on the server).')
  if (res.status === 401) throw new Error('Wrong token.')
  if (!res.ok) throw new Error(`Request failed (${res.status}).`)
  return res.json()
}

function readToken(): string {
  try { return sessionStorage.getItem('ops_token') || '' } catch { return '' }
}

function Counts({ title, data }: { title: string; data: Record<string, number> }) {
  return (
    <div className="rounded-lg border border-surface-border p-4">
      <h3 className="mb-2 text-sm font-medium">{title}</h3>
      <dl className="grid grid-cols-2 gap-1 text-sm">
        {Object.entries(data).map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-muted-foreground">{k}</dt>
            <dd className="text-right tabular-nums">{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

export function OpsView() {
  const [token, setToken] = useState(readToken())
  const [draft, setDraft] = useState('')
  const { data, error, isFetching } = useQuery({
    queryKey: ['ops-summary', token],
    queryFn: () => fetchSummary(token),
    enabled: token.length > 0,
    refetchInterval: 15_000,
    retry: false,
  })

  if (!token) {
    return (
      <div className="mx-auto max-w-md p-8">
        <h1 className="mb-4 text-xl font-semibold">Ops</h1>
        <input
          type="password"
          className="w-full rounded border border-surface-border bg-transparent p-2"
          placeholder="Ops token"
          value={draft}
          onChange={e => setDraft(e.target.value)}
        />
        <button
          className="mt-3 rounded bg-accent px-4 py-2 text-sm"
          onClick={() => {
            try { sessionStorage.setItem('ops_token', draft) } catch { /* ignore */ }
            setToken(draft)
          }}
        >
          Open
        </button>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Ops {isFetching ? '(refreshing)' : ''}</h1>
        <button
          className="text-sm underline"
          onClick={() => {
            try { sessionStorage.removeItem('ops_token') } catch { /* ignore */ }
            setToken('')
          }}
        >
          Forget token
        </button>
      </div>
      {error && <p className="text-red-400">{(error as Error).message}</p>}
      {data && (
        <>
          <p className="text-sm text-muted-foreground">
            Last {Math.round(data.window_seconds / 60)} minutes. {data.note} Server up for{' '}
            {Math.round(data.since_start_seconds / 60)} min.
          </p>
          <div className="rounded-lg border border-surface-border p-4">
            <h3 className="mb-2 text-sm font-medium">
              Health: {data.health.status}. Active alerts: {data.active_alerts.length || 'none'}
            </h3>
            <p className="text-sm text-muted-foreground">
              {Object.entries(data.health.checks).map(([k, v]) => `${k}: ${v}`).join('. ')}
            </p>
            {data.active_alerts.length > 0 && (
              <p className="mt-1 text-sm text-red-400">{data.active_alerts.join(', ')}</p>
            )}
          </div>
          <div className="grid gap-4 md:grid-cols-3">
            <Counts title="HTTP by status class" data={data.http.requests_by_status_class} />
            <Counts title="Agent turns" data={data.agent.turns} />
            <Counts title="Tool calls" data={data.agent.tool_calls} />
            <Counts title="Knowledge lookups (RAG)" data={data.rag} />
            <Counts title="Scheduler job runs" data={data.scheduler} />
            <Counts
              title="Groq"
              data={{
                '429 count': data.agent.groq_429,
                'tool parse errors': data.agent.tool_parse_errors,
                'prompt tokens': data.agent.tokens.prompt,
                'completion tokens': data.agent.tokens.completion,
              }}
            />
          </div>
          <div className="rounded-lg border border-surface-border p-4">
            <h3 className="mb-2 text-sm font-medium">Latency by route (ms, bucket upper edge)</h3>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-muted-foreground">
                  <th>Route</th><th>Count</th><th>p50</th><th>p95</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(data.http.latency_ms_by_route).map(([r, s]) => (
                  <tr key={r}>
                    <td className="font-mono">{r}</td>
                    <td>{s.count}</td><td>{s.p50 ?? '-'}</td><td>{s.p95 ?? '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="rounded-lg border border-surface-border p-4">
            <h3 className="mb-2 text-sm font-medium">Recent server errors</h3>
            {data.recent_errors.length === 0 ? (
              <p className="text-sm text-muted-foreground">None since the last restart.</p>
            ) : (
              <ul className="space-y-1 font-mono text-xs">
                {[...data.recent_errors].reverse().map((e, i) => (
                  <li key={i}>
                    {new Date(e.at * 1000).toLocaleTimeString()} {e.status} {e.route} {e.error_type}{' '}
                    request_id={e.request_id}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </div>
  )
}
