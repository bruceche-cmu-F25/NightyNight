import { useState, useRef, useCallback, useEffect } from 'react'
import gsap from 'gsap'
import { Routes, Route, useNavigate } from 'react-router-dom'
import StarField, { BackgroundMode } from './StarField'
import SettingsDrawer, { Settings } from './SettingsDrawer'
import AmbientPlayer from './AmbientPlayer'
import { THEMES } from './theme'
import { streamGenerate, NODE_PROGRESS, GenerateRequest } from './api'
import { useAuth } from './context/AuthContext'
import ProtectedRoute from './components/ProtectedRoute'
import OnboardingModal from './components/OnboardingModal'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import LibraryPage from './pages/LibraryPage'

type Phase = 'idle' | 'generating' | 'done' | 'error'

const VOICES: Record<string, string> = {
  'Christopher (gentle)':  'G17SuINrv2H9FC6nvetn',
  'Archer (deep, calm)':   'X0K9Z1Bor9SpbE1wSaoe',
  'Adam Stone (smooth)':   'NFG5qt843uXKj4pFvR7C',
  'John Doe (deep)':       'EiNlNiXeDU1pqqOPrYMO',
  'Kyle Manning':          'q8hD3YAFEqLvfbspywun',
  'True Crime Narrator':   'tZssYepgGaQmegsMEXjK',
  'Autumn Veil (warm ♀)':  'KoVIHoyLDrQyd4pGalbs',
}

const DEFAULT_SETTINGS: Settings = {
  ambient:  'auto',
  audience: 'curious adults',
  style:    'gentle bedtime',
}

const TOPIC_AMBIENT: [string[], string][] = [
  [['space', 'cosmos', 'star', 'planet', 'galaxy', 'universe', 'astro', 'nebula', 'moon', 'solar', 'orbit', 'nasa', 'rocket', 'comet', 'milky'], 'cosmos'],
  [['ocean', 'sea', 'wave', 'beach', 'marine', 'coral', 'fish', 'whale', 'deep', 'underwater', 'shark', 'tide'], 'ocean'],
  [['rain', 'storm', 'thunder', 'cloud', 'weather', 'monsoon', 'flood', 'river', 'water', 'lake', 'pond'], 'rain'],
  [['forest', 'wood', 'tree', 'nature', 'jungle', 'animal', 'bird', 'wildlife', 'plant', 'bug', 'insect', 'frog', 'cricket'], 'woods'],
  [['fire', 'volcano', 'lava', 'flame', 'campfire', 'magma', 'eruption'], 'fire'],
]

function topicToAmbient(topic: string): string {
  const lower = topic.toLowerCase()
  for (const [keywords, category] of TOPIC_AMBIENT) {
    if (keywords.some(kw => lower.includes(kw))) return category
  }
  return 'cosmos'
}

const AUDIENCE_BG: Record<string, BackgroundMode> = {
  'children (ages 4–6)':  'dreamy',
  'children (ages 7–12)': 'galaxy',
  'children (ages 13+)':  'galaxy',
}

const THEME = THEMES.default

const BG_MODES: { mode: BackgroundMode; label: string }[] = [
  { mode: 'stars',  label: '✦ Stars'  },
  { mode: 'aurora', label: '◈ Aurora' },
  { mode: 'dreamy', label: '✿ Dreamy' },
  { mode: 'galaxy', label: '✧ Galaxy' },
]

export default function App() {
  return (
    <Routes>
      <Route path="/login"    element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/library"  element={<ProtectedRoute><LibraryPage /></ProtectedRoute>} />
      <Route path="*"         element={<ProtectedRoute><MainApp /></ProtectedRoute>} />
    </Routes>
  )
}

function MainApp() {
  const { accessToken, user, logout } = useAuth()
  const navigate = useNavigate()
  const [topic,        setTopic]        = useState('')
  const [duration,     setDuration]     = useState(15)
  const [voice,        setVoice]        = useState(Object.values(VOICES)[0])
  const [bgMode,       setBgMode]       = useState<BackgroundMode>('stars')
  const [settings,     setSettings]     = useState<Settings>(DEFAULT_SETTINGS)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [bgPickerOpen, setBgPickerOpen] = useState(false)
  const [phase,        setPhase]        = useState<Phase>('idle')
  const [status,       setStatus]       = useState('')
  const [progress,     setProgress]     = useState(0)
  const [story,        setStory]        = useState('')
  const [audioUrl,     setAudioUrl]     = useState<string | null>(null)
  const [errorMsg,          setErrorMsg]          = useState('')
  const [autoPlayAmbient,   setAutoPlayAmbient]   = useState<string | null>(null)
  const [onboardingDone,    setOnboardingDone]    = useState(false)

  const abortRef          = useRef<AbortController | null>(null)
  const bgPickerRef       = useRef<HTMLDivElement>(null)
  const idleCardRef       = useRef<HTMLDivElement>(null)
  const generatingCardRef = useRef<HTMLDivElement>(null)

  // Close bg picker on outside click
  useEffect(() => {
    if (!bgPickerOpen) return
    const handler = (e: MouseEvent) => {
      if (bgPickerRef.current && !bgPickerRef.current.contains(e.target as Node))
        setBgPickerOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [bgPickerOpen])

  // Show onboarding if first login (no preferences set yet)
  const showOnboarding = !onboardingDone && !!user && !user.preferences.audience && !user.preferences.style

  // Sync settings whenever saved preferences change (login or onboarding save)
  useEffect(() => {
    if (!user?.preferences) return
    if (user.preferences.voice)    setVoice(user.preferences.voice)
    if (user.preferences.audience) setSettings(s => ({ ...s, audience: user.preferences.audience! }))
    if (user.preferences.style)    setSettings(s => ({ ...s, style: user.preferences.style! }))
  }, [user?.preferences?.voice, user?.preferences?.audience, user?.preferences?.style])

  // Auto-switch background when audience changes
  useEffect(() => {
    setBgMode(AUDIENCE_BG[settings.audience] ?? 'stars')
  }, [settings.audience])

  // Effect 1: staggered entry when idle card mounts
  useEffect(() => {
    if (phase !== 'idle' || !idleCardRef.current) return
    const targets = idleCardRef.current.querySelectorAll<HTMLElement>(
      '.logo, .tagline, .topic-input, .options, .generate-btn'
    )
    const tween = gsap.from(targets, {
      y: 24,
      autoAlpha: 0,
      duration: 1.4,
      ease: 'power2.out',
      stagger: 0.18,
      clearProps: 'all',
    })
    return () => { tween.kill() }
  }, [phase])

  // Effect 2: breathing pulse while generating
  useEffect(() => {
    if (phase !== 'generating' || !generatingCardRef.current) return
    const card = generatingCardRef.current
    const logo = card.querySelector<HTMLElement>('.logo')
    const hint = card.querySelector<HTMLElement>('.hint')
    const tweens = [
      logo && gsap.fromTo(logo,
        { scale: 1, opacity: 0.75 },
        { scale: 1.018, opacity: 1, duration: 3, ease: 'sine.inOut', repeat: -1, yoyo: true }
      ),
      hint && gsap.fromTo(hint,
        { opacity: 0.2 },
        { opacity: 0.55, duration: 2.2, ease: 'sine.inOut', repeat: -1, yoyo: true }
      ),
    ]
    return () => { tweens.forEach(t => t && t.kill()) }
  }, [phase])

  const handleGenerate = useCallback(async () => {
    if (!topic.trim()) return

    const ctrl = new AbortController()
    abortRef.current = ctrl

    setPhase('generating')
    setAutoPlayAmbient(topicToAmbient(topic))
    setProgress(0)
    setStatus('Starting…')
    setStory('')
    setAudioUrl(null)
    setErrorMsg('')

    const req: GenerateRequest = {
      topic:        topic.trim(),
      duration_min: duration,
      style:        settings.style,
      audience:     settings.audience,
      domain:       'general science',
      voice,
    }

    try {
      for await (const ev of streamGenerate(req, ctrl.signal, accessToken ?? undefined)) {
        if (ev.event === 'node_done') {
          const pct = NODE_PROGRESS[ev.node] ?? 0
          setProgress(p => Math.max(p, pct))
          setStatus(ev.message || ev.node)
        } else if (ev.event === 'done') {
          setProgress(100)
          setStory(ev.final_story)
          setAudioUrl(ev.audio_url)
          setPhase('done')
        } else if (ev.event === 'error') {
          throw new Error(ev.message)
        }
      }
    } catch (e: unknown) {
      if ((e as { name?: string }).name === 'AbortError') return
      setErrorMsg(e instanceof Error ? e.message : String(e))
      setPhase('error')
    }
  }, [topic, duration, voice, settings, accessToken])

  const handleReset = () => {
    abortRef.current?.abort()
    setPhase('idle')
    setStory('')
    setAudioUrl(null)
    setProgress(0)
    setStatus('')
    setTopic('')
  }

  return (
    <div className="root" style={{ background:
        bgMode === 'dreamy' ? 'radial-gradient(ellipse at 50% 70%, #1a1235 0%, #0e0a24 55%, #07051a 100%)'
      : bgMode === 'galaxy' ? 'radial-gradient(ellipse at 50% 80%, #0a0d2a 0%, #060818 55%, #020510 100%)'
      : THEME.bg }}>
      <StarField mode={bgMode} />
      <AmbientPlayer accent={THEME.accentColor} autoPlay={autoPlayAmbient} />

      <SettingsDrawer
        open={settingsOpen}
        settings={settings}
        onChange={setSettings}
        onClose={() => setSettingsOpen(false)}
        accent={THEME.accentColor}
      />

      {/* ── Onboarding ── */}
      {showOnboarding && <OnboardingModal onDone={() => setOnboardingDone(true)} />}

      {/* ── Top-right controls ── */}
      <div className="bg-toggle">
        {/* Scene / bg picker */}
        <div ref={bgPickerRef} style={{ position: 'relative' }}>
          <button
            className={`bg-toggle-btn ${BG_MODES.some(b => b.mode === bgMode) ? 'active' : ''}`}
            onClick={() => setBgPickerOpen(v => !v)}
            style={{ '--accent': THEME.accentColor } as React.CSSProperties}
          >
            {BG_MODES.find(b => b.mode === bgMode)?.label ?? '◉ Scene'}
          </button>
          {bgPickerOpen && (
            <div style={{
              position: 'absolute', top: 'calc(100% + 6px)', right: 0,
              background: 'rgba(8, 12, 22, 0.96)',
              border: '1px solid rgba(255,255,255,0.1)',
              borderRadius: '12px', padding: '0.4rem',
              display: 'flex', flexDirection: 'column', gap: '0.25rem',
              minWidth: '130px', zIndex: 20,
              backdropFilter: 'blur(12px)',
            }}>
              {BG_MODES.map(({ mode, label }) => (
                <button
                  key={mode}
                  className={`bg-toggle-btn ${bgMode === mode ? 'active' : ''}`}
                  onClick={() => { setBgMode(mode); setBgPickerOpen(false) }}
                  style={{ '--accent': THEME.accentColor, width: '100%', textAlign: 'left' } as React.CSSProperties}
                >
                  {label}
                </button>
              ))}
            </div>
          )}
        </div>

        <button
          className="bg-toggle-btn"
          onClick={() => navigate('/library')}
          style={{ '--accent': THEME.accentColor } as React.CSSProperties}
        >
          ☰ Library
        </button>

        <button
          className="bg-toggle-btn"
          onClick={() => setSettingsOpen(true)}
          style={{ '--accent': THEME.accentColor } as React.CSSProperties}
        >
          ⚙ Settings
        </button>

        <button
          className="bg-toggle-btn"
          onClick={logout}
          style={{ '--accent': THEME.accentColor } as React.CSSProperties}
        >
          ⏏ Sign out
        </button>
      </div>

      <div className="content">

        {/* ── Idle / Input ── */}
        {phase === 'idle' && (
          <div className="card" ref={idleCardRef}>
            <h1 className="logo">NightyNight</h1>
            <p className="tagline">A bedtime science story, made just for tonight.</p>

            <input
              className="topic-input"
              type="text"
              placeholder="What do you want to dream about tonight?"
              value={topic}
              onChange={e => setTopic(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleGenerate()}
              autoFocus
              style={{ '--accent': THEME.accentColor } as React.CSSProperties}
            />

            <div className="options">
              <label className="option-label">
                Duration
                <select
                  value={duration}
                  onChange={e => setDuration(Number(e.target.value))}
                  className="option-select"
                  style={{ '--accent': THEME.accentColor } as React.CSSProperties}
                >
                  {[8, 10, 15, 20, 25].map(d => (
                    <option key={d} value={d}>{d} min</option>
                  ))}
                </select>
              </label>

              <label className="option-label">
                Voice
                <select
                  value={voice}
                  onChange={e => setVoice(e.target.value)}
                  className="option-select"
                  style={{ '--accent': THEME.accentColor } as React.CSSProperties}
                >
                  {Object.entries(VOICES).map(([label, id]) => (
                    <option key={id} value={id}>{label}</option>
                  ))}
                </select>
              </label>
            </div>

            <button
              className="generate-btn"
              onClick={handleGenerate}
              disabled={!topic.trim()}
              style={{ '--accent': THEME.accentColor } as React.CSSProperties}
            >
              Tell me a story
            </button>
          </div>
        )}

        {/* ── Generating ── */}
        {phase === 'generating' && (
          <div className="card" ref={generatingCardRef}>
            <h1 className="logo">NightyNight</h1>
            <p className="status-text">{status}</p>
            <div className="progress-track">
              <div
                className="progress-fill"
                style={{ width: `${progress}%`, background: THEME.accentColor }}
              />
            </div>
            <p className="hint">Weaving your story…</p>
          </div>
        )}

        {/* ── Done ── */}
        {phase === 'done' && (
          <div className="story-view fade-in">
            <div className="story-header">
              <button className="back-btn" onClick={handleReset}>← New story</button>
              <button
                className="back-btn"
                onClick={() => {
                  const blob = new Blob([story], { type: 'text/plain' })
                  const url = URL.createObjectURL(blob)
                  const a = document.createElement('a')
                  a.href = url
                  a.download = `${topic.trim().replace(/\s+/g, '_') || 'story'}.txt`
                  a.click()
                  URL.revokeObjectURL(url)
                }}
              >
                ↓ Download
              </button>
            </div>

            {audioUrl && (
              <div className="player">
                <audio controls src={audioUrl} />
              </div>
            )}

            <article className="story-text">
              {story.split('\n\n').map((para, i) => (
                <p key={i}>{para}</p>
              ))}
            </article>

          </div>
        )}

        {/* ── Error ── */}
        {phase === 'error' && (
          <div className="card fade-in">
            <p className="error-text">{errorMsg}</p>
            <button
              className="generate-btn"
              onClick={handleReset}
              style={{ '--accent': THEME.accentColor } as React.CSSProperties}
            >
              Try again
            </button>
          </div>
        )}

      </div>
    </div>
  )
}
