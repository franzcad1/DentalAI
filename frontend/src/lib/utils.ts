import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'
import type { AppointmentStatus } from './api'

/** Merge Tailwind classes safely. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** Format an ISO datetime string as "10:30 AM". */
export function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  })
}

/** Format an ISO datetime string as "Mon, Jun 9". */
export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
  })
}

/** Format a date-only string (YYYY-MM-DD) as "Jun 9, 2025". */
export function formatDateShort(dateStr: string): string {
  // Append T00:00 to avoid timezone shifts when parsing date-only strings
  return new Date(`${dateStr}T00:00`).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
}

/** Return today's date as YYYY-MM-DD. */
export function todayISO(): string {
  return new Date().toISOString().split('T')[0]
}

/** Calculate days overdue from a due_date string. Positive = overdue. */
export function daysOverdue(dueDateStr: string): number {
  const due = new Date(`${dueDateStr}T00:00`)
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  return Math.floor((today.getTime() - due.getTime()) / 86_400_000)
}

/** Tailwind colour classes for appointment status badges. */
export function statusColors(status: AppointmentStatus): {
  bg: string
  text: string
  dot: string
} {
  const map: Record<AppointmentStatus, { bg: string; text: string; dot: string }> = {
    completed: {
      bg: 'bg-green-500/15',
      text: 'text-green-400',
      dot: 'bg-green-400',
    },
    confirmed: {
      bg: 'bg-blue-500/15',
      text: 'text-blue-400',
      dot: 'bg-blue-400',
    },
    pending: {
      bg: 'bg-amber-500/15',
      text: 'text-amber-400',
      dot: 'bg-amber-400',
    },
    cancelled: {
      bg: 'bg-slate-500/15',
      text: 'text-slate-400',
      dot: 'bg-slate-400',
    },
    no_show: {
      bg: 'bg-red-500/15',
      text: 'text-red-400',
      dot: 'bg-red-400',
    },
  }
  return map[status] ?? map.pending
}

/** Colour classes for event type badges. */
export function eventTypeColor(eventType: string): string {
  if (eventType.startsWith('appointment.booked')) return 'text-green-400'
  if (eventType.startsWith('appointment.reminder')) return 'text-blue-400'
  if (eventType.startsWith('recall.')) return 'text-amber-400'
  return 'text-slate-400'
}
