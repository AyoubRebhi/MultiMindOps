// localStorage-backed token store. Wrapped so call-sites don't sprinkle
// raw `localStorage.getItem(...)` everywhere and so we can swap the
// backing store later without a refactor.

const ACCESS_KEY  = 'auth:access_token'
const REFRESH_KEY = 'auth:refresh_token'

function safeGet(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

function safeSet(key: string, value: string): void {
  try {
    localStorage.setItem(key, value)
  } catch {
    /* quota or disabled storage — ignore */
  }
}

function safeRemove(key: string): void {
  try {
    localStorage.removeItem(key)
  } catch {
    /* ignore */
  }
}

export const tokenStorage = {
  getAccess:  (): string | null => safeGet(ACCESS_KEY),
  getRefresh: (): string | null => safeGet(REFRESH_KEY),

  setPair(access: string, refresh: string): void {
    safeSet(ACCESS_KEY, access)
    safeSet(REFRESH_KEY, refresh)
  },

  setAccess(access: string): void {
    safeSet(ACCESS_KEY, access)
  },

  clear(): void {
    safeRemove(ACCESS_KEY)
    safeRemove(REFRESH_KEY)
  },

  hasRefresh(): boolean {
    return !!safeGet(REFRESH_KEY)
  },
}
