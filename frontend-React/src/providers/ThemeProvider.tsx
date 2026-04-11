import { useEffect } from 'react'
import { useThemeStore } from '@/store/themeStore'

/**
 * Syncs the Zustand theme to the <html> class list.
 * Must be rendered inside QueryClientProvider / BrowserRouter so hooks work,
 * but before any layout component so the class is applied before first paint.
 */
export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const theme = useThemeStore((s) => s.theme)

  useEffect(() => {
    const root = document.documentElement
    if (theme === 'dark') {
      root.classList.add('dark')
    } else {
      root.classList.remove('dark')
    }
  }, [theme])

  // Also listen to OS pref changes while the app is open
  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const handler = (e: MediaQueryListEvent) => {
      // Only follow OS if the user hasn't manually set a preference
      const stored = localStorage.getItem('devsecops-theme')
      if (!stored) {
        useThemeStore.getState().setTheme(e.matches ? 'dark' : 'light')
      }
    }
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [])

  return <>{children}</>
}
