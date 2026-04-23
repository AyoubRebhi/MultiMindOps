import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { tasksApi } from '@/api/tasks'
import type {
  TaskCreate,
  PlanPreviewRequest,
  GenerateArtifactsRequest,
  ReviewArtifactsRequest,
  ValidatePlanRequest,
} from '@/types'

export const TASKS_KEY = ['tasks']

export function useTaskList() {
  return useQuery({
    queryKey: TASKS_KEY,
    queryFn: tasksApi.list,
    refetchInterval: 10_000, // background refresh every 10 s
  })
}

export function useTask(id: string) {
  return useQuery({
    queryKey: [...TASKS_KEY, id],
    queryFn: () => tasksApi.get(id),
    enabled: Boolean(id),
  })
}

export function useCreateTask() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: TaskCreate) => tasksApi.create(payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: TASKS_KEY }),
  })
}

export function usePlanPreview() {
  return useMutation({
    mutationFn: ({ payload, envFile }: { payload: PlanPreviewRequest; envFile?: File }) =>
      tasksApi.planPreview(payload, envFile),
  })
}

export function useGenerateArtifacts() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ payload, envFile }: { payload: GenerateArtifactsRequest; envFile?: File }) =>
      tasksApi.generate(payload, envFile),
    onSuccess: () => qc.invalidateQueries({ queryKey: TASKS_KEY }),
  })
}

export function useReviewTask() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ taskId, payload }: { taskId: string; payload: ReviewArtifactsRequest }) =>
      tasksApi.review(taskId, payload),
    onSuccess: (_, { taskId }) =>
      qc.invalidateQueries({ queryKey: [...TASKS_KEY, taskId] }),
  })
}

export function useValidatePlan() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: ValidatePlanRequest) => tasksApi.validatePlan(payload),
    onSuccess: (data) => {
      if (data.task_id) {
        qc.invalidateQueries({ queryKey: [...TASKS_KEY, data.task_id] })
      }
    },
  })
}
