import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { StepState } from '@/types'

interface TaskStore {
  // New-task wizard state
  wizard: StepState
  setWizard: (state: Partial<StepState>) => void
  resetWizard: () => void

  // Sidebar collapsed (desktop)
  sidebarCollapsed: boolean
  toggleSidebar: () => void

  // Mobile drawer (transient — not persisted)
  mobileNavOpen: boolean
  setMobileNavOpen: (open: boolean) => void
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

      mobileNavOpen: false,
      setMobileNavOpen: (open) => set({ mobileNavOpen: open }),
    }),
    {
      name: 'devsecops-ui',
      // Only persist sidebar preference, not wizard state
      partialize: (s) => ({ sidebarCollapsed: s.sidebarCollapsed }),
    }
  )
)
