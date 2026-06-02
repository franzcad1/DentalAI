import { NavLink } from 'react-router-dom'
import { CalendarDays, Bell, MessageSquare, Activity, Stethoscope } from 'lucide-react'
import { cn } from '@/lib/utils'

const NAV_ITEMS = [
  {
    to: '/',
    icon: CalendarDays,
    label: 'Schedule',
    description: "Today's appointments",
  },
  {
    to: '/recalls',
    icon: Bell,
    label: 'Recall Queue',
    description: 'Overdue patients',
  },
  {
    to: '/chat',
    icon: MessageSquare,
    label: 'Booking Chat',
    description: 'AI agent',
  },
  {
    to: '/log',
    icon: Activity,
    label: 'Agent Log',
    description: 'Live event feed',
  },
]

export function Sidebar() {
  return (
    <aside className="flex h-screen w-60 flex-shrink-0 flex-col border-r border-surface-border bg-surface-card">
      {/* Logo */}
      <div className="flex items-center gap-3 px-5 py-5 border-b border-surface-border">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent">
          <Stethoscope className="h-4 w-4 text-white" />
        </div>
        <div>
          <p className="text-sm font-semibold text-slate-100">DentalAI</p>
          <p className="text-xs text-slate-500">Practice Manager</p>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto p-3">
        <ul className="space-y-1">
          {NAV_ITEMS.map(({ to, icon: Icon, label, description }) => (
            <li key={to}>
              <NavLink
                to={to}
                end={to === '/'}
                className={({ isActive }) =>
                  cn(
                    'flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-colors',
                    isActive
                      ? 'bg-accent/15 text-accent border border-accent/25'
                      : 'text-slate-400 hover:bg-surface-raised hover:text-slate-200'
                  )
                }
              >
                {({ isActive }) => (
                  <>
                    <Icon
                      className={cn('h-4 w-4 flex-shrink-0', isActive && 'text-accent')}
                    />
                    <div>
                      <p className={cn('font-medium', isActive && 'text-accent')}>{label}</p>
                      <p className="text-xs text-slate-500">{description}</p>
                    </div>
                  </>
                )}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>

      {/* Footer */}
      <div className="border-t border-surface-border px-5 py-4">
        <p className="text-xs text-slate-600">Portfolio project · NexHealth mirror</p>
      </div>
    </aside>
  )
}
