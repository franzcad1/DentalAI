/**
 * Typed API client for the DentalAI backend.
 *
 * All responses from list endpoints are wrapped in:
 *   { code, description, data: { items: T[], total: number } }
 *
 * The agent chat endpoint returns a flat object (no envelope).
 * The events endpoint returns a plain T[] (no envelope).
 */

// ─── Types ───────────────────────────────────────────────────────────────────

export interface NexHealthResponse<T> {
  code: number
  description: string
  data: T
}

export interface PaginatedList<T> {
  items: T[]
  total: number
}

export interface Patient {
  id: number
  first_name: string
  last_name: string
  dob: string | null
  email: string | null
  phone: string | null
  created_at: string
}

export interface Provider {
  id: number
  first_name: string
  last_name: string
  specialty: string | null
}

export interface AppointmentType {
  id: number
  name: string
  duration_minutes: number
}

export type AppointmentStatus =
  | 'pending'
  | 'confirmed'
  | 'completed'
  | 'cancelled'
  | 'no_show'

export interface Appointment {
  id: number
  patient_id: number
  provider_id: number
  location_id: number
  appointment_type_id: number
  start_time: string
  end_time: string
  status: AppointmentStatus
  notes: string | null
}

export type RecallStatus = 'pending' | 'contacted' | 'scheduled' | 'dismissed'

export interface PatientRecall {
  id: number
  patient_id: number
  recall_type: string
  due_date: string
  last_contacted_at: string | null
  status: RecallStatus
}

export interface DentalEvent {
  id: number
  event_type: string
  payload: Record<string, unknown>
  fired_at: string
  status: string
}

export interface AgentToolCall {
  tool: string
  input: Record<string, unknown>
  output: string
}

export interface AgentChatResponse {
  response: string
  tool_calls: AgentToolCall[]
  session_id: string
}

// ─── HTTP core ────────────────────────────────────────────────────────────────

const BASE_URL: string =
  (import.meta.env.VITE_API_URL as string) || 'http://localhost:8000'

async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
  })
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new Error(`${res.status}: ${text}`)
  }
  return res.json() as Promise<T>
}

// ─── API functions ────────────────────────────────────────────────────────────

export const api = {
  // Health / metadata
  getHealth: () =>
    request<{ status: string; version: string; startup_id: string }>('/health'),

  // Patients
  getPatients: (params?: { name?: string; email?: string; limit?: number }) => {
    const qs = new URLSearchParams()
    if (params?.name) qs.set('name', params.name)
    if (params?.email) qs.set('email', params.email)
    if (params?.limit) qs.set('limit', String(params.limit))
    const query = qs.toString()
    return request<NexHealthResponse<PaginatedList<Patient>>>(
      `/api/v1/patients${query ? `?${query}` : ''}`
    )
  },

  // Appointments
  getAppointments: (params?: { date?: string; provider_id?: number; limit?: number }) => {
    const qs = new URLSearchParams()
    if (params?.date) qs.set('date', params.date)
    if (params?.provider_id) qs.set('provider_id', String(params.provider_id))
    qs.set('limit', String(params?.limit ?? 200))
    return request<NexHealthResponse<PaginatedList<Appointment>>>(
      `/api/v1/appointments?${qs.toString()}`
    )
  },

  // Providers
  getProviders: () =>
    request<NexHealthResponse<PaginatedList<Provider>>>('/api/v1/providers'),

  // Appointment types
  getAppointmentTypes: () =>
    request<NexHealthResponse<PaginatedList<AppointmentType>>>(
      '/api/v1/appointment_types'
    ),

  // Recalls
  getRecalls: (params?: {
    status?: RecallStatus
    due_before?: string
    limit?: number
  }) => {
    const qs = new URLSearchParams()
    if (params?.status) qs.set('status', params.status)
    if (params?.due_before) qs.set('due_before', params.due_before)
    qs.set('limit', String(params?.limit ?? 200))
    return request<NexHealthResponse<PaginatedList<PatientRecall>>>(
      `/api/v1/patient_recalls?${qs.toString()}`
    )
  },

  // Events
  getEvents: (params?: { limit?: number; event_type?: string }) => {
    const qs = new URLSearchParams()
    qs.set('limit', String(params?.limit ?? 50))
    if (params?.event_type) qs.set('event_type', params.event_type)
    return request<DentalEvent[]>(`/api/v1/events?${qs.toString()}`)
  },

  // Create appointment
  createAppointment: (body: {
    patient_id: number
    provider_id: number
    location_id: number
    appointment_type_id: number
    start_time: string
    end_time: string
    status: AppointmentStatus
    notes?: string
  }) =>
    request<NexHealthResponse<Appointment>>('/api/v1/appointments', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  // Update appointment (status, notes, times)
  updateAppointment: (
    id: number,
    patch: { status?: AppointmentStatus; notes?: string; start_time?: string; end_time?: string; provider_id?: number }
  ) =>
    request<NexHealthResponse<Appointment>>(`/api/v1/appointments/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),

  // Update recall status
  updateRecall: (id: number, patch: { status: RecallStatus }) =>
    request<NexHealthResponse<PatientRecall>>(`/api/v1/patient_recalls/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),

  // Create patient
  createPatient: (body: {
    first_name: string
    last_name: string
    email?: string
    phone?: string
    dob?: string
  }) =>
    request<NexHealthResponse<Patient>>('/api/v1/patients', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  // Locations (needed for booking form)
  getLocations: () =>
    request<NexHealthResponse<PaginatedList<{ id: number; name: string; address: string | null }>>>(
      '/api/v1/locations'
    ),

  // Sample patient names for suggestions
  getSamplePatientNames: (n = 4) =>
    request<string[]>(`/api/v1/patients/sample?n=${n}`),

  // Agent
  agentChat: (message: string, sessionId: string, signal?: AbortSignal) =>
    request<AgentChatResponse>('/api/v1/agent/chat', {
      method: 'POST',
      body: JSON.stringify({ message, session_id: sessionId }),
      signal,
    }),

  agentStatus: (sessionId: string) =>
    request<{ retrying: boolean; retry_in?: number; remaining?: number }>(
      `/api/v1/agent/status/${sessionId}`
    ),
}
