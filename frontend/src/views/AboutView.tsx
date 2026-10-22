import { Stethoscope, Github, Linkedin, CalendarDays, Bell, Users, MessageSquare, Zap } from 'lucide-react'

const STACK = [
  { label: 'Backend', items: ['Python', 'FastAPI', 'SQLAlchemy', 'SQLite', 'Alembic'] },
  { label: 'Frontend', items: ['React 18', 'TypeScript', 'Tailwind CSS', 'TanStack Query', 'Vite'] },
  { label: 'AI', items: ['Groq', 'LangChain Core', 'OpenAI function-calling format', 'driver.js (tours)'] },
  { label: 'Infrastructure', items: ['Vercel', 'Railway', 'NexHealth API schema'] },
]

const FEATURES = [
  {
    icon: CalendarDays,
    title: 'Schedule',
    desc: 'Drag appointments across providers and time slots. Optimistic updates keep the UI instant while the backend syncs.',
  },
  {
    icon: Bell,
    title: 'Recall Queue',
    desc: 'Surfaces overdue patients with one-click status updates. The AI drafts personalised outreach messages based on patient history.',
  },
  {
    icon: Users,
    title: 'Patient Directory',
    desc: 'Browse patients with a slide-over detail panel showing appointment history and active recalls side by side.',
  },
  {
    icon: MessageSquare,
    title: 'AI Agent',
    desc: 'A Groq-powered agent with real function calls. It can look up patients, find open slots, book appointments, and draft recall messages in plain English.',
  },
]

export function AboutView() {
  return (
    <div className="flex-1 overflow-y-auto px-4 sm:px-8 py-8 max-w-3xl mx-auto w-full">
      {/* Header */}
      <div className="flex items-center gap-4 mb-8">
        <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-accent flex-shrink-0">
          <Stethoscope className="h-6 w-6 text-white" />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-slate-100">DentalAI</h1>
          <p className="text-sm text-slate-400">AI-powered practice management</p>
        </div>
      </div>


      {/* What it is */}
      <section className="mb-8">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500 mb-3">What it is</h2>
        <p className="text-slate-300 leading-relaxed">
          DentalAI is a full-stack practice management tool built to explore how AI fits into real clinical workflows.
          It mirrors the NexHealth API schema and covers the three tasks that consume the most admin time in a dental office:
          scheduling, recall follow-ups, and patient outreach.
        </p>
        <p className="text-slate-300 leading-relaxed mt-3">
          The AI layer uses Groq's function-calling API so the agent can actually do things, not just answer questions.
          Ask it to find a patient, check available slots, and book an appointment and it will call the right endpoints in sequence,
          show you what it did, and confirm the result.
        </p>
        <p className="text-slate-300 leading-relaxed mt-3">
          The data model mirrors the NexHealth API schema, the dominant integration standard in dental practice management.
          The app runs on seed data today, but the structure is already aligned so it could be wired up to a real clinic's
          NexHealth account with minimal changes and go live for any practice that already uses NexHealth.
        </p>
      </section>

      {/* Why I built it */}
      <section className="mb-8">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500 mb-3">Why I built it</h2>
        <div className="flex flex-col sm:flex-row gap-5 items-start">
            <div className="flex flex-col gap-3 sm:w-40 flex-shrink-0">
            <img
              src="/franz-portrait.jpg"
              alt="Franz Cadiente"
              className="w-full rounded-xl object-cover"
              style={{ maxHeight: '180px', objectPosition: 'top' }}
            />
            <img
              src="/franz-clinic.jpg"
              alt="Franz working as a dental assistant"
              className="w-full rounded-xl object-cover"
              style={{ maxHeight: '180px', objectPosition: 'top' }}
            />
          </div>
          <div className="flex-1 space-y-3">
            <p className="text-slate-300 leading-relaxed">
              I came to Canada from the Philippines as an international student, where I studied software development.
              After graduating, obtaining permanent residency was the most practical path to building a stable career,
              and healthcare roles offered a clear route to get there.
              I worked in a dental office, first as a dental assistant, then as an office administrator, and I took the work seriously.
              But I never stopped thinking like a developer.
            </p>
            <p className="text-slate-300 leading-relaxed">
              Those years in the clinic gave me something most developers don't have: a real understanding of how dental teams actually work.
              I watched front desk staff juggle recall queues manually, copy-paste the same outreach messages, and lose time switching between tools
              to find a single patient's history. These are not edge cases. They are daily friction.
            </p>
            <p className="text-slate-300 leading-relaxed">
              DentalAI is what happens when you combine a software background with that lived experience.
              The features are not guesses at what a dental office might need. They come from watching real people do real work
              and thinking about where a well-designed AI layer would actually make a difference.
            </p>
          </div>
        </div>
      </section>

      {/* Features */}
      <section className="mb-8">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500 mb-3">Pages</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {FEATURES.map(({ icon: Icon, title, desc }) => (
            <div key={title} className="rounded-xl border border-surface-border bg-surface-card p-4">
              <div className="flex items-center gap-2 mb-2">
                <Icon className="h-4 w-4 text-accent flex-shrink-0" />
                <p className="text-sm font-medium text-slate-200">{title}</p>
              </div>
              <p className="text-xs text-slate-400 leading-relaxed">{desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Stack */}
      <section className="mb-8">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500 mb-3">Stack</h2>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {STACK.map(({ label, items }) => (
            <div key={label} className="rounded-xl border border-surface-border bg-surface-card p-4">
              <p className="text-xs font-semibold text-slate-400 mb-2">{label}</p>
              <ul className="space-y-1">
                {items.map(item => (
                  <li key={item} className="text-xs text-slate-300">{item}</li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </section>

      {/* Built by */}
      <section className="mb-4">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500 mb-3">Built by</h2>
        <div className="rounded-xl border border-surface-border bg-surface-card p-4 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <img
              src="/franz-portrait.jpg"
              alt="Franz Cadiente"
              className="h-12 w-12 rounded-full object-cover flex-shrink-0"
              style={{ objectPosition: 'top' }}
            />
            <div>
              <p className="text-sm font-medium text-slate-200">Franz Cadiente</p>
              <p className="text-xs text-slate-400 mt-0.5">AI engineer looking for the next thing.</p>
            </div>
          </div>
          <div className="flex items-center gap-3 flex-shrink-0">
            <a
              href="https://github.com/franzcad1"
              target="_blank"
              rel="noreferrer"
              className="text-slate-400 hover:text-slate-200 transition-colors"
              title="GitHub"
            >
              <Github className="h-5 w-5" />
            </a>
            <a
              href="https://linkedin.com/in/franzcadiente"
              target="_blank"
              rel="noreferrer"
              className="text-slate-400 hover:text-slate-200 transition-colors"
              title="LinkedIn"
            >
              <Linkedin className="h-5 w-5" />
            </a>
          </div>
        </div>
      </section>

      <div className="flex items-center gap-1.5 text-xs text-slate-600 mt-6">
        <Zap className="h-3 w-3" />
        <span>Portfolio project · NexHealth mirror · Not for clinical use</span>
      </div>
    </div>
  )
}
