import { useState } from 'react'
import { useAuth } from '../context/AuthContext'

const AUDIENCE_OPTIONS = [
  { value: 'curious adults',       label: 'Curious adults',    desc: 'Science with depth and wonder' },
  { value: 'children (ages 4–6)',  label: 'Kids (4–6)',        desc: 'Simple, magical, soothing'     },
  { value: 'children (ages 7–12)', label: 'Kids (7–12)',       desc: 'Fun facts and adventure'       },
  { value: 'children (ages 13+)',  label: 'Teens (13+)',       desc: 'Engaging and thought-provoking'},
  { value: 'science enthusiasts',  label: 'Science fans',      desc: 'Rich detail and discovery'     },
  { value: 'general public',       label: 'Everyone',          desc: 'Accessible and friendly'       },
]

const STYLE_OPTIONS = [
  { value: 'gentle bedtime',     label: 'Gentle bedtime',     desc: 'Soft, slow, and calming'     },
  { value: 'calm documentary',   label: 'Documentary',        desc: 'Informative and tranquil'     },
  { value: 'soft storytelling',  label: 'Soft storytelling',  desc: 'Narrative, warm, immersive'   },
]

const ACCENT = '#7fa8c8'

interface Props {
  onDone: () => void
}

export default function OnboardingModal({ onDone }: Props) {
  const { user, updatePreferences } = useAuth()
  const [audience, setAudience] = useState('curious adults')
  const [style,    setStyle]    = useState('gentle bedtime')
  const [loading,  setLoading]  = useState(false)

  const handleDone = async () => {
    setLoading(true)
    try {
      await updatePreferences({ audience, style })
    } catch { /* non-fatal */ }
    onDone()
  }

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 200,
      background: 'rgba(2, 4, 8, 0.85)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      padding: '1rem',
      backdropFilter: 'blur(6px)',
    }}>
      <div className="card fade-in" style={{ maxWidth: '440px', width: '100%' }}>
        <h1 className="logo" style={{ marginBottom: '0.25rem' }}>Welcome{user?.display_name ? `, ${user.display_name}` : ''}.</h1>
        <p className="tagline" style={{ marginBottom: '1.75rem' }}>Let's personalize your stories.</p>

        {/* Audience */}
        <p style={{ color: '#8099aa', fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '0.6rem', textAlign: 'left' }}>
          Who are the stories for?
        </p>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem', marginBottom: '1.5rem' }}>
          {AUDIENCE_OPTIONS.map(o => (
            <button
              key={o.value}
              type="button"
              onClick={() => setAudience(o.value)}
              style={{
                background: audience === o.value
                  ? `color-mix(in srgb, ${ACCENT} 12%, transparent)`
                  : 'rgba(255,255,255,0.03)',
                border: `1px solid ${audience === o.value ? ACCENT : 'rgba(255,255,255,0.08)'}`,
                borderRadius: '10px',
                padding: '0.6rem 0.75rem',
                textAlign: 'left',
                cursor: 'pointer',
                transition: 'all 0.15s',
              }}
            >
              <div style={{ color: audience === o.value ? ACCENT : 'rgba(200,210,230,0.75)', fontSize: '0.82rem', fontWeight: 500 }}>{o.label}</div>
              <div style={{ color: '#5a7080', fontSize: '0.72rem', marginTop: '2px' }}>{o.desc}</div>
            </button>
          ))}
        </div>

        {/* Style */}
        <p style={{ color: '#8099aa', fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '0.6rem', textAlign: 'left' }}>
          What tone do you prefer?
        </p>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem', marginBottom: '1.75rem' }}>
          {STYLE_OPTIONS.map(o => (
            <button
              key={o.value}
              type="button"
              onClick={() => setStyle(o.value)}
              style={{
                background: style === o.value
                  ? `color-mix(in srgb, ${ACCENT} 12%, transparent)`
                  : 'rgba(255,255,255,0.03)',
                border: `1px solid ${style === o.value ? ACCENT : 'rgba(255,255,255,0.08)'}`,
                borderRadius: '10px',
                padding: '0.6rem 0.9rem',
                textAlign: 'left',
                cursor: 'pointer',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                transition: 'all 0.15s',
              }}
            >
              <span style={{ color: style === o.value ? ACCENT : 'rgba(200,210,230,0.75)', fontSize: '0.84rem', fontWeight: 500 }}>{o.label}</span>
              <span style={{ color: '#5a7080', fontSize: '0.75rem' }}>{o.desc}</span>
            </button>
          ))}
        </div>

        <button
          className="generate-btn"
          onClick={handleDone}
          disabled={loading}
          style={{ '--accent': ACCENT } as React.CSSProperties}
        >
          {loading ? 'Saving…' : 'Start exploring'}
        </button>
      </div>
    </div>
  )
}
