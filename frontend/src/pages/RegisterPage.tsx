import { useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

const ACCENT = '#7fa8c8'

function emailValid(e: string) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e.trim())
}

function pwStrength(p: string): number {
  if (p.length < 5) return 0
  let score = 1
  if (/[A-Z]/.test(p) || /[0-9]/.test(p)) score++
  if (/[^A-Za-z0-9]/.test(p) && /[0-9]/.test(p)) score++
  return Math.min(score, 3)
}

const STRENGTH = [
  { label: 'Too short (min. 8 characters)', color: '#e05555' },
  { label: 'Weak',   color: '#e07820' },
  { label: 'Fair',   color: '#c8a020' },
  { label: 'Strong', color: '#3a9a5c' },
]

export default function RegisterPage() {
  const { register, accessToken } = useAuth()
  const navigate = useNavigate()
  const [name,         setName]         = useState('')
  const [email,        setEmail]        = useState('')
  const [emailTouched, setEmailTouched] = useState(false)
  const [password,     setPassword]     = useState('')
  const [showPw,       setShowPw]       = useState(false)
  const [confirm,      setConfirm]      = useState('')
  const [showConfirm,  setShowConfirm]  = useState(false)
  const [error,        setError]        = useState('')
  const [loading,      setLoading]      = useState(false)

  if (accessToken) return <Navigate to="/app" replace />

  const strength        = password ? pwStrength(password) : -1
  const emailError      = emailTouched && email.length > 0 && !emailValid(email)
  const confirmMismatch = confirm.length > 0 && password !== confirm
  const canSubmit       = emailValid(email) && password.length >= 8 && password === confirm && !loading

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!emailValid(email)) { setError('Please enter a valid email address'); return }
    if (password.length < 5) { setError('Password must be at least 8 characters'); return }
    if (password !== confirm) { setError('Passwords do not match'); return }
    setError('')
    setLoading(true)
    try {
      await register(email.trim().toLowerCase(), password, name.trim() || undefined)
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
            {/* Name */}
            <input
              className="topic-input"
              type="text"
              placeholder="Name (optional)"
              value={name}
              onChange={e => setName(e.target.value)}
              style={{ '--accent': ACCENT, marginBottom: '0.75rem' } as React.CSSProperties}
            />

            {/* Email */}
            <input
              className="topic-input"
              type="email"
              placeholder="Email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              onBlur={() => setEmailTouched(true)}
              required
              style={{
                '--accent': emailError ? '#e05555' : ACCENT,
                marginBottom: emailError ? '0.25rem' : '0.75rem',
              } as React.CSSProperties}
            />
            {emailError && (
              <p style={{ color: '#e05555', fontSize: '0.8rem', marginBottom: '0.5rem', textAlign: 'left' }}>
                Please enter a valid email address
              </p>
            )}

            {/* Password + strength */}
            <div style={{ position: 'relative', marginBottom: '0.25rem' }}>
              <input
                className="topic-input"
                type={showPw ? 'text' : 'password'}
                placeholder="Password"
                value={password}
                maxLength={128}
                onChange={e => setPassword(e.target.value)}
                required
                style={{ '--accent': ACCENT, paddingRight: '3.5rem', width: '100%', boxSizing: 'border-box' } as React.CSSProperties}
              />
              <button
                type="button"
                onClick={() => setShowPw(v => !v)}
                style={{
                  position: 'absolute', right: '0.75rem', top: '50%', transform: 'translateY(-50%)',
                  background: 'none', border: 'none', color: '#8099aa', cursor: 'pointer',
                  fontSize: '0.78rem', padding: 0,
                }}
              >
                {showPw ? 'Hide' : 'Show'}
              </button>
            </div>

            {password && (
              <div style={{ marginBottom: '0.75rem' }}>
                <div style={{ display: 'flex', gap: '4px', marginBottom: '4px' }}>
                  {[1, 2, 3].map(i => (
                    <div key={i} style={{
                      height: '3px', flex: 1, borderRadius: '2px',
                      background: strength >= i ? STRENGTH[Math.min(strength, 3)].color : '#2a3a4a',
                      transition: 'background 0.2s',
                    }} />
                  ))}
                </div>
                <p style={{ fontSize: '0.75rem', color: STRENGTH[Math.max(strength, 0)].color, margin: 0, textAlign: 'left' }}>
                  {STRENGTH[Math.max(strength, 0)].label}
                </p>
              </div>
            )}

            {/* Confirm password */}
            <div style={{ position: 'relative', marginBottom: confirmMismatch ? '0.25rem' : '1rem' }}>
              <input
                className="topic-input"
                type={showConfirm ? 'text' : 'password'}
                placeholder="Confirm password"
                value={confirm}
                maxLength={128}
                onChange={e => setConfirm(e.target.value)}
                required
                style={{
                  '--accent': confirmMismatch ? '#e05555' : ACCENT,
                  paddingRight: '3.5rem', width: '100%', boxSizing: 'border-box',
                } as React.CSSProperties}
              />
              <button
                type="button"
                onClick={() => setShowConfirm(v => !v)}
                style={{
                  position: 'absolute', right: '0.75rem', top: '50%', transform: 'translateY(-50%)',
                  background: 'none', border: 'none', color: '#8099aa', cursor: 'pointer',
                  fontSize: '0.78rem', padding: 0,
                }}
              >
                {showConfirm ? 'Hide' : 'Show'}
              </button>
            </div>
            {confirmMismatch && (
              <p style={{ color: '#e05555', fontSize: '0.8rem', marginBottom: '0.75rem', textAlign: 'left' }}>
                Passwords do not match
              </p>
            )}

            {error && <p className="error-text" style={{ marginBottom: '0.75rem' }}>{error}</p>}

            <button
              className="generate-btn"
              type="submit"
              disabled={!canSubmit}
              style={{ '--accent': ACCENT, opacity: canSubmit ? 1 : 0.5, cursor: canSubmit ? 'pointer' : 'not-allowed' } as React.CSSProperties}
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
