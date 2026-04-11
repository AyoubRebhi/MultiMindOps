import { Outlet } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { Navbar } from './Navbar'

export function Layout() {
  return (
    <div className="flex h-screen bg-white dark:bg-surface-950 text-slate-900 dark:text-white overflow-hidden transition-colors duration-250">
      <Sidebar />
      <div className="flex flex-col flex-1 min-w-0">
        <Navbar />
        <main className="flex-1 overflow-y-auto bg-slate-50/50 dark:bg-transparent">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
