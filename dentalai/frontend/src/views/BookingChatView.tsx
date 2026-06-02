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
import { MessageSquare, Send, ChevronDown, ChevronUp, Bot, User, Zap } from 'lucide-react'
import { api, type AgentToolCall } from '@/lib/api'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'

// ─── Types ────────────────────────────────────────────────────────────────────

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  toolCalls?: AgentToolCall[]
  isLoading?: boolean
  error?: string
  timestamp: Date
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
      <div className={cn('max-w-[75%]', isUser && 'items-end flex flex-col')}>
        <div
          className={cn(
            'rounded-2xl px-4 py-2.5 text-sm leading-relaxed',
            isUser
              ? 'rounded-tr-sm bg-accent text-white'
              : 'rounded-tl-sm bg-surface-card border border-surface-border text-slate-200'
          )}
        >
          {msg.isLoading ? (
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
              <span className="text-xs">Thinking…</span>
            </div>
          ) : msg.error ? (
            <span className="text-red-400">{msg.error}</span>
          ) : (
            <p className="whitespace-pre-wrap">{msg.content}</p>
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

const SUGGESTIONS = [
  'Book a cleaning for patient 3 with any available provider this week',
  'Which patients are most overdue for a recall?',
  'Draft a recall message for patient 7',
  'Show me patient 5\'s context and recall status',
]

// ─── Main view ────────────────────────────────────────────────────────────────

export function BookingChatView() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [sessionId] = useState(() => `chat-${Date.now()}`)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // Scroll to bottom whenever messages change
  useEffect(() => {
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

    try {
      const result = await api.agentChat(trimmed, sessionId)
      setMessages((prev) =>
        prev.map((m) =>
          m.id === loadingMsg.id
            ? {
                ...m,
                content: result.response,
                toolCalls: result.tool_calls,
                isLoading: false,
              }
            : m
        )
      )
    } catch (err) {
      const errorMsg =
        err instanceof Error && err.message.includes('503')
          ? 'Agent unavailable — set OPENAI_API_KEY in backend/.env and restart.'
          : String(err)

      setMessages((prev) =>
        prev.map((m) =>
          m.id === loadingMsg.id
            ? { ...m, content: '', error: errorMsg, isLoading: false }
            : m
        )
      )
    } finally {
      setIsLoading(false)
      inputRef.current?.focus()
    }
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    sendMessage(input)
  }

  return (
    <div className="flex h-screen flex-col">
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-surface-border px-6 py-4">
        <MessageSquare className="h-5 w-5 text-accent" />
        <div>
          <h1 className="text-base font-semibold text-slate-100">Booking Chat</h1>
          <p className="text-xs text-slate-400">AI scheduling and recall agent · gpt-4o-mini</p>
        </div>
        <div className="ml-auto flex items-center gap-1.5 rounded-full border border-green-500/30 bg-green-500/10 px-3 py-1">
          <span className="h-1.5 w-1.5 rounded-full bg-green-400 animate-pulse" />
          <span className="text-xs text-green-400">Agent ready</span>
        </div>
      </div>

      {/* Messages area */}
      <ScrollArea className="flex-1 px-6">
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
                {SUGGESTIONS.map((s) => (
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

      {/* Input bar */}
      <div className="border-t border-surface-border px-6 py-4">
        <form onSubmit={handleSubmit} className="flex items-center gap-3">
          <Input
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask the agent to book, reschedule, or draft a recall message…"
            disabled={isLoading}
            className="flex-1 h-11 bg-surface-raised text-sm"
            autoFocus
          />
          <Button type="submit" disabled={!input.trim() || isLoading} size="icon" className="h-11 w-11">
            {isLoading ? (
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
            ) : (
              <Send className="h-4 w-4" />
            )}
          </Button>
        </form>
        <p className="mt-2 text-center text-xs text-slate-600">
          Session: <code className="text-slate-500">{sessionId}</code>
        </p>
      </div>
    </div>
  )
}
