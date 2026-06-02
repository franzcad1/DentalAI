import { useState, useEffect } from 'react'
import { Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { getToken } from '@/lib/api'
import { Layout } from '@/components/Layout'
import { TokenGate } from '@/components/TokenGate'
import { ScheduleView } from '@/views/ScheduleView'
import { RecallQueueView } from '@/views/RecallQueueView'
import { BookingChatView } from '@/views/BookingChatView'
import { AgentLogView } from '@/views/AgentLogView'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 30_000, // 30 s — reduces unnecessary refetches
    },
  },
})

export default function App() {
  const [hasToken, setHasToken] = useState(false)

  useEffect(() => {
    // Check for token on mount (handles VITE_DEV_TOKEN and localStorage)
    setHasToken(Boolean(getToken()))
  }, [])

  if (!hasToken) {
    return <TokenGate onAuthenticated={() => setHasToken(true)} />
  }

  return (
    <QueryClientProvider client={queryClient}>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<ScheduleView />} />
          <Route path="/recalls" element={<RecallQueueView />} />
          <Route path="/chat" element={<BookingChatView />} />
          <Route path="/log" element={<AgentLogView />} />
        </Route>
      </Routes>
    </QueryClientProvider>
  )
}
