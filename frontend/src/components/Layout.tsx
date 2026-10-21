import { Outlet } from 'react-router-dom'
import { Sidebar } from './Sidebar'

export function Layout() {
  return (
    <div className="flex h-screen overflow-hidden bg-surface-base text-slate-200">
      <Sidebar />
      <main className="flex-1 overflow-hidden pb-16 md:pb-0 flex flex-col">
        <Outlet />
      </main>
    </div>
  )
}
