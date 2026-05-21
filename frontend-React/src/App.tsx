import { Routes, Route } from 'react-router-dom'
import { Layout }        from '@/components/layout/Layout'
import Dashboard         from '@/pages/Dashboard'
import NewTask           from '@/pages/NewTask'
import WorkflowPage      from '@/pages/WorkflowPage'
import TaskList          from '@/pages/TaskList'
import TaskDetail        from '@/pages/TaskDetail'
import TaskReview        from '@/pages/TaskReview'
import ProjectList       from '@/pages/ProjectList'
import NewProject        from '@/pages/NewProject'
import ProjectDetail     from '@/pages/ProjectDetail'
import NotFound          from '@/pages/NotFound'

export default function App() {
  return (
    <Routes>
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
          <Route path="workflow" element={<WorkflowPage />} />
          <Route path=":id" element={<TaskDetail />} />
          <Route path=":id/review" element={<TaskReview />} />
        </Route>
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  )
}
