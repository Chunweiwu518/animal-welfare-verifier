const DEFAULT_API_BASE_URL =
  typeof window === 'undefined' ? 'http://localhost:5173' : ''
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? DEFAULT_API_BASE_URL

export interface AuthUser {
  authenticated: boolean
  id?: number
  provider?: string
  display_name?: string
  avatar_url?: string
}

export async function fetchCurrentUser(): Promise<AuthUser> {
  const response = await fetch(`${API_BASE_URL}/api/auth/me`, {
    credentials: 'include',
  })
  if (!response.ok) {
    return { authenticated: false }
  }
  return (await response.json()) as AuthUser
}

export function buildLineLoginUrl(redirectPath: string = window.location.pathname): string {
  const params = new URLSearchParams({ redirect_to: redirectPath })
  return `${API_BASE_URL}/api/auth/line/login?${params}`
}

export async function logout(): Promise<void> {
  await fetch(`${API_BASE_URL}/api/auth/logout`, {
    method: 'POST',
    credentials: 'include',
  })
}
