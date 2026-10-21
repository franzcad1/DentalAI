import { Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { Layout } from '@/components/Layout'
import { ScheduleView } from '@/views/ScheduleView'
import { RecallQueueView } from '@/views/RecallQueueView'
import { BookingChatView } from '@/views/BookingChatView'
import { AgentLogView } from '@/views/AgentLogView'
import { PatientsView } from '@/views/PatientsView'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 30_000,
    },
  },
})

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<ScheduleView />} />
          <Route path="/recalls" element={<RecallQueueView />} />
          <Route path="/chat" element={<BookingChatView />} />
          <Route path="/patients" element={<PatientsView />} />
          <Route path="/log" element={<AgentLogView />} />
        </Route>
      </Routes>
    </QueryClientProvider>
  )
}
