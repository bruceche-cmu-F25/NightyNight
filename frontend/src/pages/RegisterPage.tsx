import { useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

const ACCENT = '#7fa8c8'

export default function RegisterPage() {
  const { register, accessToken } = useAuth()
  const navigate = useNavigate()
  const [email,    setEmail]    = useState('')
  const [password, setPassword] = useState('')
  const [confirm,  setConfirm]  = useState('')
  const [name,     setName]     = useState('')
  const [error,    setError]    = useState('')
  const [loading,  setLoading]  = useState(false)

  if (accessToken) return <Navigate to="/app" replace />

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (password !== confirm) { setError('Passwords do not match'); return }
    setError('')
    setLoading(true)
    try {
      await register(email, password, name || undefined)
      navigate('/app')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Registration failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="root" style={{ background: 'radial-gradient(ellipse at 50% 80%, #0a0f1a 0%, #050810 60%, #020408 100%)' }}>
      <div className="content">
        <div className="card fade-in">
          <h1 className="logo">NightyNight</h1>
          <p className="tagline">Create your account</p>

          <form onSubmit={handleSubmit} style={{ width: '100%' }}>
            <input
              className="topic-input"
              type="text"
              placeholder="Name (optional)"
              value={name}
              onChange={e => setName(e.target.value)}
              style={{ '--accent': ACCENT, marginBottom: '0.75rem' } as React.CSSProperties}
            />
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
              style={{ '--accent': ACCENT, marginBottom: '0.75rem' } as React.CSSProperties}
            />
            <input
              className="topic-input"
              type="password"
              placeholder="Confirm password"
              value={confirm}
              onChange={e => setConfirm(e.target.value)}
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
              {loading ? 'Creating account…' : 'Create account'}
            </button>
          </form>

          <p style={{ color: '#8099aa', marginTop: '1.25rem', fontSize: '0.9rem' }}>
            Already have an account?{' '}
            <Link to="/login" style={{ color: ACCENT }}>Sign in</Link>
          </p>
        </div>
      </div>
    </div>
  )
}
