import { createContext, useContext, useEffect, useState, ReactNode } from 'react'

export interface UserPrefs {
  voice:    string | null
  audience: string | null
  style:    string | null
}

export interface AuthUser {
  id:                  string
  email:               string
  display_name:        string | null
  preferences:         UserPrefs
  daily_count:         number
  monthly_count:       number
  story_count?:        number
  plan:                'free' | 'premium'
  subscription_status: string
  is_premium:          boolean
}

interface AuthContextType {
  accessToken: string | null
  user:        AuthUser | null
  loading:     boolean
  login:              (email: string, password: string) => Promise<void>
  register:           (email: string, password: string, displayName?: string) => Promise<void>
  loginWithGoogle:    (idToken: string) => Promise<void>
  logout:             () => Promise<void>
  updatePreferences:  (prefs: Partial<UserPrefs>) => Promise<void>
}

const AuthContext = createContext<AuthContextType | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [accessToken, setAccessToken] = useState<string | null>(null)
  const [user,        setUser]        = useState<AuthUser | null>(null)
  const [loading,     setLoading]     = useState(true)

  // Restore session on mount via httpOnly refresh cookie
  useEffect(() => {
    fetch('/auth/refresh', { method: 'POST', credentials: 'include' })
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (data) { setAccessToken(data.access_token); setUser(data.user) }
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const _post = async (path: string, body: object) => {
    let res: Response
    try {
      res = await fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        credentials: 'include',
      })
    } catch {
      throw new Error('Network error — please check your connection')
    }
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Request failed' }))
      const msg = Array.isArray(err.detail)
        ? (err.detail[0]?.msg ?? 'Request failed')
        : (err.detail || 'Request failed')
      throw new Error(msg)
    }
    return res.json()
  }

  const login = async (email: string, password: string) => {
    const data = await _post('/auth/login', { email, password })
    setAccessToken(data.access_token); setUser(data.user)
  }

  const register = async (email: string, password: string, displayName?: string) => {
    const data = await _post('/auth/register', { email, password, display_name: displayName })
    setAccessToken(data.access_token); setUser(data.user)
  }

  const loginWithGoogle = async (idToken: string) => {
    const data = await _post('/auth/google', { id_token: idToken })
    setAccessToken(data.access_token); setUser(data.user)
  }

  const logout = async () => {
    await fetch('/auth/logout', { method: 'POST', credentials: 'include' }).catch(() => {})
    setAccessToken(null); setUser(null)
  }

  const updatePreferences = async (prefs: Partial<UserPrefs>) => {
    const res = await fetch('/auth/me', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${accessToken}` },
      body: JSON.stringify(prefs),
      credentials: 'include',
    })
    if (!res.ok) throw new Error('Failed to save preferences')
    const updated = await res.json()
    setUser(u => u ? { ...u, preferences: updated.preferences } : null)
  }

  return (
    <AuthContext.Provider value={{ accessToken, user, loading, login, register, loginWithGoogle, logout, updatePreferences }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
