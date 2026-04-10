import { create } from 'zustand'
import { persist } from 'zustand/middleware'

type Theme = 'dark' | 'light'

interface ThemeStore {
  theme: Theme
  setTheme: (t: Theme) => void
  toggle: () => void
}

/** Resolve which theme to start with — stored value → system pref → dark */
function resolveInitial(): Theme {
  if (typeof window === 'undefined') return 'dark'
  const stored = localStorage.getItem('devsecops-theme')
  if (stored === 'light' || stored === 'dark') return stored
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export const useThemeStore = create<ThemeStore>()(
  persist(
    (set) => ({
      theme: resolveInitial(),
      setTheme: (theme) => set({ theme }),
      toggle: () => set((s) => ({ theme: s.theme === 'dark' ? 'light' : 'dark' })),
    }),
    {
      name: 'devsecops-theme',
      partialize: (s) => ({ theme: s.theme }),
    }
  )
)
