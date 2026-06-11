import { useEffect, useRef } from 'react'
import { BackgroundMode } from './StarField'

export interface Settings {
  ambient:  string
  audience: string
  style:    string
}

interface Props {
  open:       boolean
  settings:   Settings
  onChange:   (s: Settings) => void
  onClose:    () => void
  accent:     string
  bgMode:     BackgroundMode
  onBgChange: (m: BackgroundMode) => void
}

const BG_MODES: { mode: BackgroundMode; label: string }[] = [
  { mode: 'stars',  label: '✦ Stars'  },
  { mode: 'aurora', label: '◈ Aurora' },
  { mode: 'dreamy', label: '✿ Dreamy' },
  { mode: 'galaxy', label: '✧ Galaxy' },
]

const AMBIENT_OPTIONS  = ['auto', 'fire', 'rain', 'ocean', 'woods', 'cosmos', 'none']
const AUDIENCE_OPTIONS = [
  'curious adults',
  'science enthusiasts',
  'general public',
  'children (ages 4–6)',
  'children (ages 7–12)',
  'children (ages 13+)',
]
const STYLE_OPTIONS = ['gentle bedtime', 'calm documentary', 'soft storytelling']

export default function SettingsDrawer({ open, settings, onChange, onClose, accent, bgMode, onBgChange }: Props) {
  const drawerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (drawerRef.current && !drawerRef.current.contains(e.target as Node)) onClose()
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open, onClose])

  const set = (key: keyof Settings) => (e: React.ChangeEvent<HTMLSelectElement>) =>
    onChange({ ...settings, [key]: e.target.value })

  return (
    <div className={`drawer-backdrop ${open ? 'open' : ''}`}>
      <div className="drawer" ref={drawerRef} style={{ '--accent': accent } as React.CSSProperties}>
        <div className="drawer-header">
          <span className="drawer-title">Settings</span>
          <button className="drawer-close" onClick={onClose}>✕</button>
        </div>

        <div className="drawer-body">
          <label className="drawer-label" style={{ marginBottom: '0.5rem' }}>Background</label>
          <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap', marginBottom: '1.25rem' }}>
            {BG_MODES.map(({ mode, label }) => (
              <button
                key={mode}
                onClick={() => onBgChange(mode)}
                className={`bg-toggle-btn ${bgMode === mode ? 'active' : ''}`}
                style={{ '--accent': accent } as React.CSSProperties}
              >
                {label}
              </button>
            ))}
          </div>

          <label className="drawer-label">
            Ambient sound
            <select className="drawer-select" value={settings.ambient} onChange={set('ambient')}>
              {AMBIENT_OPTIONS.map(o => <option key={o} value={o}>{o}</option>)}
            </select>
          </label>

          <label className="drawer-label">
            Audience
            <select className="drawer-select" value={settings.audience} onChange={set('audience')}>
              {AUDIENCE_OPTIONS.map(o => <option key={o} value={o}>{o}</option>)}
            </select>
          </label>

          <label className="drawer-label">
            Narration style
            <select className="drawer-select" value={settings.style} onChange={set('style')}>
              {STYLE_OPTIONS.map(o => <option key={o} value={o}>{o}</option>)}
            </select>
          </label>
        </div>
      </div>
    </div>
  )
}
