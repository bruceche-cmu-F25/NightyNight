import { useState, useRef, useCallback } from 'react'
import StarField, { BackgroundMode } from './StarField'
import SettingsDrawer, { Settings } from './SettingsDrawer'
import AmbientPlayer from './AmbientPlayer'
import { THEMES } from './theme'
import { streamGenerate, NODE_PROGRESS, GenerateRequest } from './api'

type Phase = 'idle' | 'generating' | 'done' | 'error'

const VOICES: Record<string, string> = {
  'Christopher (gentle)':  'G17SuINrv2H9FC6nvetn',
  'Archer (deep, calm)':   'X0K9Z1Bor9SpbE1wSaoe',
  'Adam Stone (smooth)':   'NFG5qt843uXKj4pFvR7C',
  'Autumn Veil (warm ♀)':  'KoVIHoyLDrQyd4pGalbs',
}

const DEFAULT_SETTINGS: Settings = {
  ambient:  'auto',
  audience: 'curious adults',
  style:    'gentle bedtime',
}

const BG_MODES: { mode: BackgroundMode; label: string }[] = [
  { mode: 'stars',  label: '✦ Stars'  },
  { mode: 'aurora', label: '◈ Aurora' },
]

const THEME = THEMES.default

export default function App() {
  const [topic,        setTopic]        = useState('')
  const [duration,     setDuration]     = useState(15)
  const [voice,        setVoice]        = useState(Object.values(VOICES)[0])
  const [bgMode,       setBgMode]       = useState<BackgroundMode>('stars')
  const [settings,     setSettings]     = useState<Settings>(DEFAULT_SETTINGS)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [phase,        setPhase]        = useState<Phase>('idle')
  const [status,       setStatus]       = useState('')
  const [progress,     setProgress]     = useState(0)
  const [story,        setStory]        = useState('')
  const [audioUrl,     setAudioUrl]     = useState<string | null>(null)
  const [errorMsg,     setErrorMsg]     = useState('')

  const abortRef = useRef<AbortController | null>(null)

  const handleGenerate = useCallback(async () => {
    if (!topic.trim()) return

    setPhase('generating')
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
      ambient:      settings.ambient,
    }

    try {
      for await (const ev of streamGenerate(req)) {
        if (ev.event === 'node_done') {
          const pct = NODE_PROGRESS[ev.node] ?? progress
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
      setErrorMsg(e instanceof Error ? e.message : String(e))
      setPhase('error')
    }
  }, [topic, duration, voice, settings, progress])

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
    <div className="root" style={{ background: THEME.bg }}>
      <StarField theme={THEME} mode={bgMode} />
      <AmbientPlayer accent={THEME.accentColor} />

      <SettingsDrawer
        open={settingsOpen}
        settings={settings}
        onChange={setSettings}
        onClose={() => setSettingsOpen(false)}
        accent={THEME.accentColor}
      />

      {/* ── Top-right controls ── */}
      <div className="bg-toggle">
        {BG_MODES.map(({ mode, label }) => (
          <button
            key={mode}
            className={`bg-toggle-btn ${bgMode === mode ? 'active' : ''}`}
            onClick={() => setBgMode(mode)}
            style={{ '--accent': THEME.accentColor } as React.CSSProperties}
          >
            {label}
          </button>
        ))}
        <button
          className="bg-toggle-btn"
          onClick={() => setSettingsOpen(true)}
          style={{ '--accent': THEME.accentColor } as React.CSSProperties}
        >
          ⚙ Settings
        </button>
      </div>

      <div className="content">

        {/* ── Idle / Input ── */}
        {phase === 'idle' && (
          <div className="card fade-in">
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
          <div className="card fade-in">
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
