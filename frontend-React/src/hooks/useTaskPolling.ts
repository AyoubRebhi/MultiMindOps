import { useEffect, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { tasksApi } from '@/api/tasks'
import { isTerminalStatus } from '@/lib/utils'
import { TASKS_KEY } from './useTasks'
import type { TaskResponse } from '@/types'

/**
 * Polls GET /tasks/:id every `intervalMs` until the task reaches
 * a terminal status (completed | failed | human_approved*).
 * Updates the query cache in place — any component watching
 * useTask(id) will re-render automatically.
 */
export function useTaskPolling(
  taskId: string | undefined,
  {
    intervalMs = 3000,
    onComplete,
  }: { intervalMs?: number; onComplete?: (task: TaskResponse) => void } = {}
) {
  const qc = useQueryClient()
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const stoppedRef = useRef(false)

  useEffect(() => {
    if (!taskId) return
    stoppedRef.current = false

    async function poll() {
      if (stoppedRef.current) return
      try {
        const task = await tasksApi.get(taskId!)
        qc.setQueryData([...TASKS_KEY, taskId], task)
        qc.invalidateQueries({ queryKey: TASKS_KEY })

        if (isTerminalStatus(task.status)) {
          stoppedRef.current = true
          onComplete?.(task)
          return
        }
        if (task.status === 'awaiting_human_review') {
          stoppedRef.current = true
          onComplete?.(task)
          return
        }
      } catch {
        // Network hiccup — keep polling
      }
      timerRef.current = setTimeout(poll, intervalMs)
    }

    poll()

    return () => {
      stoppedRef.current = true
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [taskId, intervalMs, qc, onComplete])
}
