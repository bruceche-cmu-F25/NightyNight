import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import gsap from 'gsap'
import { useAuth } from '../context/AuthContext'

interface StoryCard {
  id:           string
  topic:        string
  story_text:   string | null
  audio_url:    string | null
  duration_min: number | null
  created_at:   string
}

const ACCENT = '#7fa8c8'

export default function LibraryPage() {
  const { accessToken } = useAuth()
  const navigate = useNavigate()
  const [stories,  setStories]  = useState<StoryCard[]>([])
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const [loading,  setLoading]  = useState(true)
  const [error,    setError]    = useState('')

  const articleRefs = useRef<Record<string, HTMLElement | null>>({})

  useEffect(() => {
    fetch('/auth/stories', {
      headers: { Authorization: `Bearer ${accessToken}` },
      credentials: 'include',
    })
      .then(r => r.ok ? r.json() : Promise.reject('Failed to load stories'))
      .then(setStories)
      .catch(() => setError('Could not load story history.'))
      .finally(() => setLoading(false))
  }, [accessToken])

  // Initialise all article elements to height 0 after stories load
  useEffect(() => {
    stories.forEach(s => {
      const el = articleRefs.current[s.id]
      if (el) gsap.set(el, { height: 0, overflow: 'hidden' })
    })
  }, [stories])

  const handleToggle = (id: string) => {
    const el = articleRefs.current[id]
    if (!el) return
    const opening = !expanded[id]
    if (opening) {
      gsap.to(el, { height: 'auto', duration: 0.4, ease: 'power2.out' })
    } else {
      gsap.to(el, { height: 0, duration: 0.3, ease: 'power2.in' })
    }
    setExpanded(prev => ({ ...prev, [id]: opening }))
  }

  return (
    <div className="root" style={{ background: 'radial-gradient(ellipse at 50% 80%, #0a0f1a 0%, #050810 60%, #020408 100%)' }}>
      <div className="content">
        <div className="story-view fade-in">
          <div className="story-header">
            <button className="back-btn" onClick={() => navigate('/app')}>← Back</button>
          </div>

          <h2 style={{ color: ACCENT, marginBottom: '1.5rem', fontFamily: 'Lora, serif' }}>Your Stories</h2>

          {loading && <p style={{ color: '#8099aa' }}>Loading…</p>}
          {error   && <p className="error-text">{error}</p>}
          {!loading && !error && stories.length === 0 && (
            <p style={{ color: '#8099aa' }}>No stories yet. Go generate one!</p>
          )}

          {stories.map(s => (
            <div key={s.id} style={{
              background: 'rgba(127,168,200,0.07)',
              border: '1px solid rgba(127,168,200,0.15)',
              borderRadius: '12px',
              padding: '1rem 1.25rem',
              marginBottom: '1rem',
            }}>
              <p style={{ color: '#cce0f0', fontWeight: 500, marginBottom: '0.25rem' }}>{s.topic}</p>
              <p style={{ color: '#8099aa', fontSize: '0.8rem', marginBottom: s.audio_url ? '0.75rem' : '0.5rem' }}>
                {new Date(s.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })}
                {s.duration_min ? ` · ${s.duration_min} min` : ''}
              </p>
              {s.audio_url && (
                <audio controls src={s.audio_url} style={{ width: '100%', marginBottom: '0.75rem' }} />
              )}
              {s.story_text && (
                <>
                  <button
                    onClick={() => handleToggle(s.id)}
                    style={{
                      background: 'none', border: 'none', padding: 0,
                      color: ACCENT, fontSize: '0.78rem', cursor: 'pointer',
                      letterSpacing: '0.04em',
                    }}
                  >
                    {expanded[s.id] ? '▲ Hide story' : '▼ Read story'}
                  </button>
                  <article
                    ref={el => { articleRefs.current[s.id] = el }}
                    style={{
                      marginTop: '1rem',
                      fontFamily: 'Lora, serif',
                      fontSize: '0.95rem',
                      lineHeight: 1.85,
                      color: 'rgba(230,228,245,0.8)',
                    }}
                  >
                    {s.story_text.split('\n\n').map((para, i) => (
                      <p key={i} style={{ marginBottom: '1.2em' }}>{para}</p>
                    ))}
                  </article>
                </>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
