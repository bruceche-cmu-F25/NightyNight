import { useEffect, useRef, useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID || '793594470575-7c0ftlsergt8vrvhms2pij9osm2akdfd.apps.googleusercontent.com'
const ACCENT = '#7fa8c8'

export default function LoginPage() {
  const { login, loginWithGoogle, accessToken } = useAuth()
  const navigate = useNavigate()
  const [email,    setEmail]    = useState('')
  const [password, setPassword] = useState('')
  const [error,    setError]    = useState('')
  const [loading,  setLoading]  = useState(false)
  const googleBtnRef = useRef<HTMLDivElement>(null)

  if (accessToken) return <Navigate to="/app" replace />

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await login(email, password)
      navigate('/app')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    const clientId = GOOGLE_CLIENT_ID
    if (!clientId) return

    const init = () => {
      const g = (window as any).google
      if (!g || !googleBtnRef.current) return
      try {
        g.accounts.id.initialize({
          client_id: clientId,
          callback: async ({ credential }: { credential: string }) => {
            try {
              await loginWithGoogle(credential)
              navigate('/app')
            } catch (err) {
              setError(err instanceof Error ? err.message : 'Google login failed')
            }
          },
        })
        g.accounts.id.renderButton(googleBtnRef.current, {
          theme: 'filled_black', size: 'large', width: 320,
        })
      } catch { /* renderButton failed */ }
    }

    if ((window as any).google) {
      init()
    } else {
      (window as any).onGoogleLibraryLoad = init
    }
  }, [])

  return (
    <div className="root" style={{ background: 'radial-gradient(ellipse at 50% 80%, #0a0f1a 0%, #050810 60%, #020408 100%)' }}>
      <div className="content">
        <div className="card fade-in">
          <h1 className="logo">NightyNight</h1>
          <p className="tagline">Sign in to your account</p>

          <form onSubmit={handleSubmit} style={{ width: '100%' }}>
            <input
              className="topic-input"
              type="email"
              placeholder="Email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              required
              style={{ '--accent': ACCENT, marginBottom: '0.75rem' } as React.CSSProperties}
            />
            <input
              className="topic-input"
              type="password"
              placeholder="Password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              required
              style={{ '--accent': ACCENT, marginBottom: '1rem' } as React.CSSProperties}
            />
            {error && <p className="error-text" style={{ marginBottom: '0.75rem' }}>{error}</p>}
            <button
              className="generate-btn"
              type="submit"
              disabled={loading}
              style={{ '--accent': ACCENT } as React.CSSProperties}
            >
              {loading ? 'Signing in…' : 'Sign in'}
            </button>
          </form>

          {GOOGLE_CLIENT_ID && (
            <div style={{ marginTop: '1rem', width: '100%', display: 'flex', justifyContent: 'center' }}>
              <div ref={googleBtnRef} />
            </div>
          )}

          <p style={{ color: '#8099aa', marginTop: '1.25rem', fontSize: '0.9rem' }}>
            No account?{' '}
            <Link to="/register" style={{ color: ACCENT }}>Create one</Link>
          </p>
        </div>
      </div>
    </div>
  )
}
