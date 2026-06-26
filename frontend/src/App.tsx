import { useState, useRef, useCallback, useEffect } from 'react'
import gsap from 'gsap'
import { Routes, Route, useNavigate } from 'react-router-dom'
import StarField, { BackgroundMode } from './StarField'
import SettingsDrawer from './SettingsDrawer'
import AmbientPlayer from './AmbientPlayer'
import { THEMES } from './theme'
import { streamGenerate, NODE_PROGRESS, GenerateRequest } from './api'
import { useAuth } from './context/AuthContext'
import { useStorySettings } from './hooks/useStorySettings'
import ProtectedRoute from './components/ProtectedRoute'
import OnboardingModal from './components/OnboardingModal'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import LibraryPage from './pages/LibraryPage'
import LandingPage from './pages/LandingPage'

type Phase = 'idle' | 'generating' | 'done' | 'error'

type VoiceEntry = { label: string; id: string }

const FALLBACK_FREE_VOICES: VoiceEntry[] = [
  { label: 'Blake', id: 'Blake' },
  { label: 'Craig', id: 'Craig' },
  { label: 'Clive', id: 'Clive' },
]

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
      <Route path="/"         element={<LandingPage />} />
      <Route path="/login"    element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/library"  element={<ProtectedRoute><LibraryPage /></ProtectedRoute>} />
      <Route path="*"         element={<ProtectedRoute><MainApp /></ProtectedRoute>} />
    </Routes>
  )
}

function MainApp() {
  const { accessToken, user, logout } = useAuth()
  const { voice, setVoice, settings, setSettings } = useStorySettings()
  const navigate = useNavigate()
  const [topic,        setTopic]        = useState('')
  const [duration,     setDuration]     = useState(15)
  const [bgMode,       setBgMode]       = useState<BackgroundMode>('stars')
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [bgPickerOpen, setBgPickerOpen] = useState(false)
  const [phase,        setPhase]        = useState<Phase>('idle')
  const [status,       setStatus]       = useState('')
  const [progress,     setProgress]     = useState(0)
  const [story,        setStory]        = useState('')
  const [audioUrl,     setAudioUrl]     = useState<string | null>(null)
  const [ttsError,     setTtsError]     = useState<string | null>(null)
  const [errorMsg,          setErrorMsg]          = useState('')
  const [autoPlayAmbient,   setAutoPlayAmbient]   = useState<string | null>(null)
  const [onboardingDone,    setOnboardingDone]    = useState(false)
  const [freeVoices,    setFreeVoices]    = useState<VoiceEntry[]>(FALLBACK_FREE_VOICES)
  const [premiumVoices, setPremiumVoices] = useState<VoiceEntry[]>([])

  const abortRef          = useRef<AbortController | null>(null)
  const bgPickerRef       = useRef<HTMLDivElement>(null)
  const generatingCardRef = useRef<HTMLDivElement>(null)
  const storyViewRef      = useRef<HTMLDivElement>(null)
  const audioRef          = useRef<HTMLAudioElement>(null)
  const progressTweenRef  = useRef<gsap.core.Tween | null>(null)
  const progressProxy     = useRef({ value: 0 })

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

  // Fetch voice catalog from backend on mount
  useEffect(() => {
    fetch('/voices')
      .then(r => r.json())
      .then(data => {
        if (Array.isArray(data.free))    setFreeVoices(data.free)
        if (Array.isArray(data.premium)) setPremiumVoices(data.premium)
      })
      .catch(() => { /* keep fallback voices */ })
  }, [])

  // Auto-switch background when audience changes
  useEffect(() => {
    setBgMode(AUDIENCE_BG[settings.audience] ?? 'stars')
  }, [settings.audience])

  // Effect 2: generating animations — logo glow, dot wave, shimmer sweep
  useEffect(() => {
    if (phase !== 'generating' || !generatingCardRef.current) return
    const card    = generatingCardRef.current
    const logo    = card.querySelector<HTMLElement>('.logo')
    const dots    = card.querySelectorAll<HTMLElement>('.dot')
    const shimmer = card.querySelector<HTMLElement>('.progress-shimmer')

    const tweens = [
      // Soft glow pulse — more visible than the previous 1.8% scale
      logo && gsap.fromTo(logo,
        { opacity: 0.55, textShadow: '0 0 20px rgba(180,180,255,0)' },
        { opacity: 1, textShadow: '0 0 40px rgba(180,180,255,0.45)', duration: 3, ease: 'sine.inOut', repeat: -1, yoyo: true }
      ),
      // Three dots wave: each fades in 0.25 s after the previous
      dots.length > 0 && gsap.fromTo(dots,
        { autoAlpha: 0.15 },
        { autoAlpha: 1, duration: 0.6, ease: 'sine.inOut', repeat: -1, yoyo: true, stagger: 0.25 }
      ),
      // Shimmer sweeps across the filled portion of the progress bar
      shimmer && gsap.fromTo(shimmer,
        { xPercent: -100 },
        { xPercent: 200, duration: 1.8, ease: 'power1.inOut', repeat: -1, repeatDelay: 0.6 }
      ),
    ]
    return () => { tweens.forEach(t => t && t.kill()) }
  }, [phase])

  // Effect 3: staggered entrance when story view mounts
  useEffect(() => {
    if (phase !== 'done' || !storyViewRef.current) return
    const view    = storyViewRef.current
    const header  = view.querySelector('.story-header')
    const player  = view.querySelector('.player')
    const article = view.querySelector('.story-text')

    const tl = gsap.timeline()
    if (header)  tl.from(header,  { y: 18, autoAlpha: 0, duration: 0.55, ease: 'power2.out', clearProps: 'all' })
    if (player)  tl.from(player,  { y: 18, autoAlpha: 0, duration: 0.55, ease: 'power2.out', clearProps: 'all' }, '-=0.3')
    if (article) tl.from(article, { y: 18, autoAlpha: 0, duration: 0.7,  ease: 'power2.out', clearProps: 'all' }, '-=0.3')
    return () => { tl.kill() }
  }, [phase])

  // Effect 4: auto-play audio when URL arrives
  useEffect(() => {
    if (!audioUrl || !audioRef.current) return
    audioRef.current.play().catch(() => {})
  }, [audioUrl])

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
    setTtsError(null)
    setErrorMsg('')

    const req: GenerateRequest = {
      topic:        topic.trim(),
      duration_min: duration,
      style:        settings.style,
      audience:     settings.audience,
      domain:       'general science',
      voice,
    }

    const startCreep = (from: number, to: number, duration: number) => {
      progressTweenRef.current?.kill()
      progressProxy.current.value = from
      progressTweenRef.current = gsap.to(progressProxy.current, {
        value: to, duration, ease: 'none',
        onUpdate: () => {
          const v = Math.round(progressProxy.current.value)
          setProgress(p => v > p ? v : p)
        },
      })
    }

    try {
      for await (const ev of streamGenerate(req, ctrl.signal, accessToken ?? undefined)) {
        if (ev.event === 'node_done') {
          const pct = NODE_PROGRESS[ev.node] ?? 0
          progressTweenRef.current?.kill()
          setProgress(p => Math.max(p, pct))

          if (ev.node === 'assemble_chapters') {
            setStatus('Polishing story…')
            startCreep(pct, 91, 90)          // creep 80→91 over 90 s
          } else if (ev.node === 'polish_story') {
            setStatus('Synthesizing audio…')
            startCreep(pct, 99, 60)          // creep 92→99 over 60 s
          } else {
            setStatus(ev.message || ev.node)
          }
        } else if (ev.event === 'done') {
          progressTweenRef.current?.kill()
          setProgress(100)
          setStory(ev.final_story)
          setAudioUrl(ev.audio_url)
          setTtsError(ev.tts_error ?? null)
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
    progressTweenRef.current?.kill()
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
          <div className="card">
            <h1 className="logo">NightyNight</h1>
            <p className="tagline">A bedtime science story, made just for tonight.</p>

            <input
              className="topic-input"
              type="text"
              placeholder="What do you want to dream about tonight?"
              value={topic}
              maxLength={200}
              onChange={e => setTopic(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleGenerate()}
              autoFocus
              style={{ '--accent': THEME.accentColor } as React.CSSProperties}
            />
            {topic.length > 0 && (
              <p style={{
                alignSelf: 'flex-end',
                marginTop: '-1rem',
                fontSize: '0.7rem',
                color: topic.length >= 180 ? '#e09977' : 'rgba(180,180,200,0.3)',
                letterSpacing: '0.04em',
              }}>
                {topic.length}/200
              </p>
            )}

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
                  <optgroup label="Standard">
                    {freeVoices.map(v => (
                      <option key={v.id} value={v.id}>{v.label}</option>
                    ))}
                  </optgroup>
                  <optgroup label="Premium ✦">
                    {premiumVoices.map(v => (
                      <option key={v.id} value={v.id} disabled={!user?.is_premium}>
                        {v.label}{!user?.is_premium ? ' · Premium' : ''}
                      </option>
                    ))}
                  </optgroup>
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
              >
                <div className="progress-shimmer" />
              </div>
            </div>
            <p className="hint">
              Weaving your story<span className="dot">.</span><span className="dot">.</span><span className="dot">.</span>
            </p>
          </div>
        )}

        {/* ── Done ── */}
        {phase === 'done' && (
          <div className="story-view" ref={storyViewRef}>
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

            {audioUrl ? (
              <div className="player">
                <audio ref={audioRef} controls src={audioUrl} />
              </div>
            ) : ttsError ? (
              <p className="error-text" style={{ marginBottom: '1rem' }}>
                Audio generation failed — please try again.
              </p>
            ) : null}

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
