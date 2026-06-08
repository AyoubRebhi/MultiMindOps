import { Routes, Route }     from 'react-router-dom'
import { Layout }             from '@/components/layout/Layout'
import { AuthLayout }         from '@/components/layout/AuthLayout'
import { ProtectedRoute }     from '@/components/auth/ProtectedRoute'
import { GuestOnlyRoute }     from '@/components/auth/GuestOnlyRoute'
import Dashboard              from '@/pages/Dashboard'
import NewTask                from '@/pages/NewTask'
import TaskList               from '@/pages/TaskList'
import TaskDetail             from '@/pages/TaskDetail'
import TaskReview             from '@/pages/TaskReview'
import ProjectList            from '@/pages/ProjectList'
import NewProject             from '@/pages/NewProject'
import ProjectDetail          from '@/pages/ProjectDetail'
import LoginPage              from '@/pages/LoginPage'
import RegisterPage           from '@/pages/RegisterPage'
import UnauthorizedPage       from '@/pages/UnauthorizedPage'
import NotFound               from '@/pages/NotFound'

export default function App() {
  return (
    <Routes>
      {/* Public auth routes — redirect to / if already signed in */}
      <Route element={<GuestOnlyRoute />}>
        <Route element={<AuthLayout />}>
          <Route path="/login"    element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
        </Route>
      </Route>

      {/* 403 — accessible regardless of auth state */}
      <Route path="/unauthorized" element={<UnauthorizedPage />} />

      {/* App shell — everything below requires auth */}
      <Route element={<ProtectedRoute />}>
        <Route element={<Layout />}>
          <Route index element={<Dashboard />} />
          <Route path="projects">
            <Route index element={<ProjectList />} />
            <Route path="new" element={<NewProject />} />
            <Route path=":id" element={<ProjectDetail />} />
          </Route>
          <Route path="tasks">
            <Route index element={<TaskList />} />
            <Route path="new" element={<NewTask />} />
            <Route path=":id" element={<TaskDetail />} />
            <Route path=":id/review" element={<TaskReview />} />
          </Route>
          <Route path="*" element={<NotFound />} />
        </Route>
      </Route>
    </Routes>
  )
}
