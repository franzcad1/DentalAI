/**
 * Booking Chat View — the portfolio showpiece.
 *
 * A chat interface backed by POST /agent/chat. Each agent response
 * shows the answer text plus an expandable "tool calls" section
 * displaying every tool the agent invoked, its input, and its output.
 *
 * Conversation is preserved for the lifetime of the browser session
 * via the session_id state variable.
 */
import { useState, useRef, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { MessageSquare, Send, ChevronDown, ChevronUp, Bot, User, Zap, Lightbulb, X, Trash2 } from 'lucide-react'
import { api, type AgentToolCall } from '@/lib/api'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'

// ─── Types ────────────────────────────────────────────────────────────────────

interface RetryStatus {
  retrying: boolean
  retry_in?: number
  remaining?: number
}

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  toolCalls?: AgentToolCall[]
  isLoading?: boolean
  error?: string
  timestamp: Date
  retryStatus?: RetryStatus
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function ToolCallPanel({ calls }: { calls: AgentToolCall[] }) {
  const [open, setOpen] = useState(false)

  return (
    <div className="mt-2">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-300 transition-colors"
      >
        <Zap className="h-3 w-3" />
        {calls.length} tool call{calls.length !== 1 ? 's' : ''}
        {open ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
      </button>

      {open && (
        <div className="mt-2 space-y-2 animate-fade-in">
          {calls.map((tc, i) => (
            <div
              key={i}
              className="rounded-lg border border-surface-border bg-surface-base p-3 text-xs"
            >
              {/* Tool name */}
              <p className="mb-2 font-mono font-medium text-accent">{tc.tool}()</p>

              {/* Input */}
              <div className="mb-2">
                <p className="mb-1 text-slate-500 uppercase tracking-wide text-[10px]">Input</p>
                <pre className="overflow-x-auto whitespace-pre-wrap rounded bg-surface-raised px-2 py-1.5 text-slate-400 font-mono text-[11px] leading-relaxed">
                  {JSON.stringify(tc.input, null, 2)}
                </pre>
              </div>

              {/* Output */}
              <div>
                <p className="mb-1 text-slate-500 uppercase tracking-wide text-[10px]">Output</p>
                <pre className="max-h-40 overflow-y-auto overflow-x-auto whitespace-pre-wrap rounded bg-surface-raised px-2 py-1.5 text-slate-400 font-mono text-[11px] leading-relaxed">
                  {tc.output.length > 800 ? tc.output.slice(0, 800) + '\n…(truncated)' : tc.output}
                </pre>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

const BANNER_KEY = 'dentalai_rate_banner_dismissed'

function RateLimitBanner() {
  const [visible, setVisible] = useState(() => {
    try { return !localStorage.getItem(BANNER_KEY) } catch { return true }
  })

  if (!visible) return null

  return (
    <div className="flex items-start gap-3 border-b border-yellow-500/20 bg-yellow-500/5 px-4 sm:px-6 py-2.5">
      <span className="mt-0.5 h-2 w-2 flex-shrink-0 rounded-full bg-yellow-400 animate-pulse" />
      <p className="flex-1 text-xs text-yellow-300/80 leading-relaxed">
        Responses may take <span className="font-medium text-yellow-300">over 1 minute</span> due to Groq's free-tier rate limits. If you hit an error, wait a moment and try again.
      </p>
      <button
        onClick={() => {
          setVisible(false)
          try { localStorage.setItem(BANNER_KEY, '1') } catch {}
        }}
        className="flex-shrink-0 text-yellow-500/60 hover:text-yellow-300 transition-colors"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  )
}

function LoadingIndicator({ startedAt, retryStatus }: { startedAt: Date; retryStatus?: RetryStatus }) {
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    const id = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startedAt.getTime()) / 1000))
    }, 1000)
    return () => clearInterval(id)
  }, [startedAt])

  const label =
    elapsed < 5  ? 'Thinking…' :
    elapsed < 15 ? `Still thinking… (${elapsed}s)` :
    elapsed < 30 ? `This is taking longer than usual… (${elapsed}s)` :
                   `Waiting on the AI provider… (${elapsed}s)`

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-2 text-slate-400">
        <div className="flex gap-1">
          {[0, 1, 2].map((i) => (
            <span
              key={i}
              className="inline-block h-1.5 w-1.5 rounded-full bg-slate-500 animate-bounce"
              style={{ animationDelay: `${i * 150}ms` }}
            />
          ))}
        </div>
        <span className={`text-xs transition-colors ${elapsed >= 15 ? 'text-yellow-400' : ''}`}>{label}</span>
      </div>
      {retryStatus?.retrying && retryStatus.remaining != null && (
        <p className="text-[11px] text-orange-400/90 leading-tight">
          Rate limited — retrying in {retryStatus.remaining}s
        </p>
      )}
    </div>
  )
}

function MessageBubble({ msg }: { msg: Message }) {
  const isUser = msg.role === 'user'

  return (
    <div className={cn('flex gap-3', isUser && 'flex-row-reverse')}>
      {/* Avatar */}
      <div
        className={cn(
          'flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full text-white',
          isUser ? 'bg-slate-700' : 'bg-accent'
        )}
      >
        {isUser ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
      </div>

      {/* Content */}
      <div className={cn('min-w-0 max-w-[85%] sm:max-w-[75%]', isUser && 'items-end flex flex-col')}>
        <div
          className={cn(
            'rounded-2xl px-4 py-2.5 text-sm leading-relaxed min-w-0 overflow-hidden',
            isUser
              ? 'rounded-tr-sm bg-accent text-white'
              : 'rounded-tl-sm bg-surface-card border border-surface-border text-slate-200'
          )}
        >
          {msg.isLoading ? (
            <LoadingIndicator startedAt={msg.timestamp} retryStatus={msg.retryStatus} />
          ) : msg.error ? (
            <span className="text-red-400">{msg.error}</span>
          ) : (
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                p: ({ children }) => <p className="mb-1 last:mb-0">{children}</p>,
                table: ({ children }) => (
                  <div className="overflow-x-auto mt-2 mb-1">
                    <table className="min-w-full text-xs border-collapse">{children}</table>
                  </div>
                ),
                thead: ({ children }) => <thead className="border-b border-slate-600">{children}</thead>,
                th: ({ children }) => <th className="px-3 py-1.5 text-left font-semibold text-slate-300 whitespace-nowrap">{children}</th>,
                td: ({ children }) => <td className="px-3 py-1.5 text-slate-300 border-t border-slate-700/50 whitespace-nowrap">{children}</td>,
                tr: ({ children }) => <tr className="hover:bg-slate-700/30 transition-colors">{children}</tr>,
                strong: ({ children }) => <strong className="font-semibold text-slate-100">{children}</strong>,
                ol: ({ children }) => <ol className="list-decimal list-inside space-y-0.5 my-1">{children}</ol>,
                ul: ({ children }) => <ul className="list-disc list-inside space-y-0.5 my-1">{children}</ul>,
                li: ({ children }) => <li className="text-slate-300">{children}</li>,
              }}
            >
              {msg.content}
            </ReactMarkdown>
          )}
        </div>

        {/* Tool calls (assistant only) */}
        {!isUser && msg.toolCalls && msg.toolCalls.length > 0 && (
          <div className="ml-1 w-full max-w-full">
            <ToolCallPanel calls={msg.toolCalls} />
          </div>
        )}

        <p className="mt-1 text-[10px] text-slate-600 px-1">
          {msg.timestamp.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })}
        </p>
      </div>
    </div>
  )
}

// ─── Suggested prompts ────────────────────────────────────────────────────────

interface SuggestionGroup {
  label: string
  prompts: string[]
}

function buildSuggestionGroups(names: string[]): SuggestionGroup[] {
  const [a, b, c, d] = [...names, 'a patient', 'a patient', 'a patient', 'a patient']
  return [
    {
      label: 'Scheduling',
      prompts: [
        `Search for ${a} and book a cleaning this week`,
        'What are the appointments for tomorrow?',
        'What are the appointments for today?',
        'Find available slots for next Monday',
      ],
    },
    {
      label: 'Patients',
      prompts: [
        'List all patients',
        `Look up ${b} and show their details`,
        'List patients by Dr. Lopez',
        'Add a new patient named Jane Doe, DOB 1990-05-12',
      ],
    },
    {
      label: 'Recalls',
      prompts: [
        'Which patients are most overdue for a recall?',
        `Find ${c} and draft a recall message`,
        `Look up ${d} and show their recall status`,
        'Show the full recall queue',
      ],
    },
  ]
}

// ─── Suggestions Panel ────────────────────────────────────────────────────────

function SuggestionsPanel({
  groups,
  onSelect,
  onClose,
}: {
  groups: SuggestionGroup[]
  onSelect: (s: string) => void
  onClose: () => void
}) {
  return (
    <div className="flex flex-col w-64 flex-shrink-0 border-l border-surface-border bg-surface-card">
      <div className="flex items-center justify-between px-4 py-3 border-b border-surface-border">
        <div className="flex items-center gap-2">
          <Lightbulb className="h-4 w-4 text-accent" />
          <span className="text-sm font-medium text-slate-200">Suggestions</span>
        </div>
        <button onClick={onClose} className="text-red-500 hover:text-red-400 transition-colors">
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-3 space-y-4">
        {groups.map(group => (
          <div key={group.label}>
            <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-widest text-slate-500">{group.label}</p>
            <div className="space-y-1">
              {group.prompts.map(prompt => (
                <button
                  key={prompt}
                  onClick={() => onSelect(prompt)}
                  className="w-full rounded-lg border border-surface-border bg-surface-base px-3 py-2 text-left text-xs text-slate-400 hover:bg-surface-raised hover:text-slate-200 hover:border-accent/40 transition-colors leading-relaxed"
                >
                  {prompt}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── Main view ────────────────────────────────────────────────────────────────

const SESSION_KEY = 'dentalai_chat_session_id'
const MESSAGES_KEY = 'dentalai_chat_messages'

function loadSession(): string {
  try {
    return sessionStorage.getItem(SESSION_KEY) || (() => {
      const id = `chat-${Date.now()}`
      sessionStorage.setItem(SESSION_KEY, id)
      return id
    })()
  } catch {
    return `chat-${Date.now()}`
  }
}

function loadMessages(): Message[] {
  try {
    const raw = sessionStorage.getItem(MESSAGES_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw) as Array<Omit<Message, 'timestamp'> & { timestamp: string }>
    return parsed.map((m) => ({ ...m, timestamp: new Date(m.timestamp) }))
  } catch {
    return []
  }
}

function saveMessages(msgs: Message[]) {
  try {
    sessionStorage.setItem(MESSAGES_KEY, JSON.stringify(msgs))
  } catch {}
}

export function BookingChatView() {
  const [messages, setMessages] = useState<Message[]>(loadMessages)
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [sessionId] = useState(loadSession)
  const [suggestionGroups, setSuggestionGroups] = useState<SuggestionGroup[]>(buildSuggestionGroups([]))
  const [showSuggestions, setShowSuggestions] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  // Keep a flat list for the empty-state quick buttons
  const suggestions = suggestionGroups.map(g => g.prompts[0])

  // Load dynamic suggestions from the backend
  useEffect(() => {
    api.getSamplePatientNames(4).then((names) => {
      setSuggestionGroups(buildSuggestionGroups(names))
    }).catch(() => {})
  }, [])

  // Persist messages and scroll to bottom whenever messages change
  useEffect(() => {
    saveMessages(messages)
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function sendMessage(text: string) {
    const trimmed = text.trim()
    if (!trimmed || isLoading) return

    const userMsg: Message = {
      id: `u-${Date.now()}`,
      role: 'user',
      content: trimmed,
      timestamp: new Date(),
    }
    const loadingMsg: Message = {
      id: `a-${Date.now()}`,
      role: 'assistant',
      content: '',
      isLoading: true,
      timestamp: new Date(),
    }

    setMessages((prev) => [...prev, userMsg, loadingMsg])
    setInput('')
    setIsLoading(true)

    const abort = new AbortController()
    abortRef.current = abort

    // Poll for retry status while the agent is working
    const pollInterval = setInterval(async () => {
      try {
        const status = await api.agentStatus(sessionId)
        setMessages((prev) =>
          prev.map((m) =>
            m.id === loadingMsg.id ? { ...m, retryStatus: status } : m
          )
        )
      } catch { /* ignore poll errors */ }
    }, 1000)

    try {
      const result = await api.agentChat(trimmed, sessionId, abort.signal)
      clearInterval(pollInterval)
      setMessages((prev) =>
        prev.map((m) =>
          m.id === loadingMsg.id
            ? {
                ...m,
                content: result.response,
                toolCalls: result.tool_calls,
                isLoading: false,
                retryStatus: undefined,
              }
            : m
        )
      )
    } catch (err) {
      clearInterval(pollInterval)
      const msg = err instanceof Error ? err.message : String(err)
      // Extract the detail message from the backend error body if present
      let detail = msg
      try {
        const jsonStart = msg.indexOf('{')
        if (jsonStart !== -1) {
          const parsed = JSON.parse(msg.slice(jsonStart))
          if (parsed?.detail) detail = parsed.detail
        }
      } catch { /* ignore */ }

      const errorMsg =
        err instanceof Error && err.name === 'AbortError'
          ? null  // user cancelled — remove the bubble silently
          : msg.includes('503')
          ? 'Agent unavailable — the backend is not reachable.'
          : msg.includes('429') || msg.includes('rate limit') || msg.includes('too large')
          ? detail
          : msg

      if (errorMsg === null) {
        // Cancelled by user — remove the loading bubble
        setMessages((prev) => prev.filter((m) => m.id !== loadingMsg.id))
      } else {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === loadingMsg.id
              ? { ...m, content: '', error: errorMsg, isLoading: false }
              : m
          )
        )
      }
    } finally {
      setIsLoading(false)
      inputRef.current?.focus()
    }
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    sendMessage(input)
  }

  function cancelRequest() {
    abortRef.current?.abort()
    abortRef.current = null
  }

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-surface-border px-4 sm:px-6 py-4">
        <MessageSquare className="h-5 w-5 text-accent" />
        <div>
          <h1 className="text-base font-semibold text-slate-100">Booking Chat</h1>
          <p className="text-xs text-slate-400">AI scheduling and recall agent</p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={() => setShowSuggestions(v => !v)}
            className="flex items-center gap-1.5 rounded-lg border border-yellow-500/40 bg-yellow-500/10 px-3 py-1.5 text-xs text-yellow-400 hover:bg-yellow-500/20 transition-colors"
          >
            <Lightbulb className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">Suggestions</span>
          </button>
          {messages.length > 0 && (
            <button
              onClick={() => {
                setMessages([])
                try { sessionStorage.removeItem(MESSAGES_KEY) } catch {}
              }}
              className="flex items-center gap-1.5 rounded-lg border border-surface-border px-3 py-1.5 text-xs text-slate-400 hover:border-red-500/40 hover:bg-red-500/10 hover:text-red-400 transition-colors"
              title="Clear chat history"
            >
              <Trash2 className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">Clear</span>
            </button>
          )}
          <div className="flex items-center gap-1.5 rounded-full border border-green-500/30 bg-green-500/10 px-3 py-1">
            <span className="h-1.5 w-1.5 rounded-full bg-green-400 animate-pulse" />
            <span className="text-xs text-green-400 hidden sm:inline">Agent ready</span>
            <span className="text-xs text-green-400 sm:hidden">Ready</span>
          </div>
        </div>
      </div>

      {/* Rate-limit notice banner */}
      <RateLimitBanner />

      {/* Body: chat + optional suggestions panel */}
      <div className="flex flex-1 min-h-0">

      {/* Messages area */}
      <ScrollArea className="flex-1 px-4 sm:px-6">
        <div className="py-6 space-y-5">
          {/* Welcome state */}
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-accent/20">
                <Bot className="h-7 w-7 text-accent" />
              </div>
              <h2 className="mb-1 text-lg font-semibold text-slate-200">DentalAI Agent</h2>
              <p className="mb-6 max-w-sm text-sm text-slate-400">
                I can search for appointment slots, book appointments, retrieve patient records,
                manage recall queues, and draft outreach messages.
              </p>
              <div className="grid w-full max-w-lg grid-cols-1 gap-2">
                {suggestions.map((s) => (
                  <button
                    key={s}
                    onClick={() => sendMessage(s)}
                    className="rounded-lg border border-surface-border bg-surface-card px-4 py-2.5 text-left text-sm text-slate-400 hover:bg-surface-raised hover:text-slate-200 hover:border-accent/40 transition-colors"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Messages */}
          {messages.map((msg) => (
            <MessageBubble key={msg.id} msg={msg} />
          ))}
          <div ref={bottomRef} />
        </div>
      </ScrollArea>

      {/* Suggestions panel */}
      {showSuggestions && (
        <SuggestionsPanel
          groups={suggestionGroups}
          onSelect={(s) => { sendMessage(s); setShowSuggestions(false) }}
          onClose={() => setShowSuggestions(false)}
        />
      )}

      </div>{/* end body flex */}

      {/* Input bar */}
      <div className="border-t border-surface-border px-4 sm:px-6 py-4">
        <form onSubmit={handleSubmit} className="flex items-center gap-3">
          <Input
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask the agent to book, reschedule, or draft a recall message…"
            disabled={isLoading}
            className="flex-1 h-11 bg-surface-raised text-base sm:text-sm"
            autoFocus
          />
          {isLoading ? (
            <Button type="button" onClick={cancelRequest} size="icon" className="h-11 w-11 bg-red-600 hover:bg-red-700 border-red-500" title="Cancel">
              <X className="h-4 w-4" />
            </Button>
          ) : (
            <Button type="submit" disabled={!input.trim()} size="icon" className="h-11 w-11">
              <Send className="h-4 w-4" />
            </Button>
          )}
        </form>
        <p className="mt-2 text-center text-xs text-slate-600">
          Session: <code className="text-slate-500">{sessionId}</code>
        </p>
      </div>
    </div>
  )
}
