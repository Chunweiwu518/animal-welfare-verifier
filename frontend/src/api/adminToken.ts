const STORAGE_KEY = 'aw:admin-token'

export function getAdminToken(): string {
  if (typeof window === 'undefined') return ''
  try {
    return window.localStorage.getItem(STORAGE_KEY) ?? ''
  } catch {
    return ''
  }
}

export function setAdminToken(token: string): void {
  if (typeof window === 'undefined') return
  const trimmed = token.trim()
  try {
    if (trimmed) {
      window.localStorage.setItem(STORAGE_KEY, trimmed)
    } else {
      window.localStorage.removeItem(STORAGE_KEY)
    }
  } catch {
    // ignore
  }
}

export function adminAuthHeaders(): Record<string, string> {
  const token = getAdminToken()
  return token ? { 'X-Admin-Token': token } : {}
}
