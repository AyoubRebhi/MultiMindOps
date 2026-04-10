import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { StepState } from '@/types'

interface TaskStore {
  // New-task wizard state
  wizard: StepState
  setWizard: (state: Partial<StepState>) => void
  resetWizard: () => void

  // Sidebar collapsed
  sidebarCollapsed: boolean
  toggleSidebar: () => void
}

const initialWizard: StepState = { step: 'form' }

export const useTaskStore = create<TaskStore>()(
  persist(
    (set) => ({
      wizard: initialWizard,
      setWizard: (state) =>
        set((s) => ({ wizard: { ...s.wizard, ...state } })),
      resetWizard: () => set({ wizard: initialWizard }),

      sidebarCollapsed: false,
      toggleSidebar: () =>
        set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
    }),
    {
      name: 'devsecops-ui',
      // Only persist sidebar preference, not wizard state
      partialize: (s) => ({ sidebarCollapsed: s.sidebarCollapsed }),
    }
  )
)
