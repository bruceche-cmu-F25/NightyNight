import { createContext, useContext, useEffect, useState, ReactNode } from 'react'

export interface UserPrefs {
  voice:    string | null
  audience: string | null
  style:    string | null
}

export interface AuthUser {
  id:           string
  email:        string
  display_name: string | null
  preferences:  UserPrefs
  daily_count:  number
  monthly_count: number
  story_count?: number
}

interface AuthContextType {
  accessToken: string | null
  user:        AuthUser | null
  loading:     boolean
  login:            (email: string, password: string) => Promise<void>
  register:         (email: string, password: string, displayName?: string) => Promise<void>
  loginWithGoogle:  (idToken: string) => Promise<void>
  logout:           () => Promise<void>
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
    const res = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      credentials: 'include',
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Request failed' }))
      throw new Error(err.detail || 'Request failed')
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

  return (
    <AuthContext.Provider value={{ accessToken, user, loading, login, register, loginWithGoogle, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
