import { useEffect, useRef, useState } from 'react'

const SOUNDS = [
  { label: 'Rain',   icon: '🌧', file: '/sounds/rain/Light rain recordings mixed settings-01.wav' },
  { label: 'Ocean',  icon: '🌊', file: '/sounds/ocean/ocean01.mp3' },
  { label: 'Fire',   icon: '🔥', file: '/sounds/fire/fire01.mp3' },
  { label: 'Woods',  icon: '🌲', file: '/sounds/woods/woods01.mp3' },
  { label: 'Cosmos', icon: '🌌', file: '/sounds/cosmos/cosmos01.wav' },
]

interface Props { accent: string }

export default function AmbientPlayer({ accent }: Props) {
  const [open,     setOpen]     = useState(false)
  const [selected, setSelected] = useState<string | null>(null)
  const [playing,  setPlaying]  = useState(false)
  const [volume,   setVolume]   = useState(0.35)
  const audioRef  = useRef<HTMLAudioElement | null>(null)
  const panelRef  = useRef<HTMLDivElement>(null)

  // init audio element once
  useEffect(() => {
    const a = new Audio()
    a.loop = true
    a.volume = volume
    audioRef.current = a
    return () => { a.pause() }
  }, [])

  // close panel on outside click
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const play = (label: string, file: string) => {
    const a = audioRef.current!
    if (selected === label) {
      // toggle play/pause
      if (playing) { a.pause(); setPlaying(false) }
      else         { a.play(); setPlaying(true) }
    } else {
      a.src = file
      a.volume = volume
      a.play().then(() => setPlaying(true)).catch(() => {})
      setSelected(label)
    }
  }

  const handleVolume = (e: React.ChangeEvent<HTMLInputElement>) => {
    const v = Number(e.target.value)
    setVolume(v)
    if (audioRef.current) audioRef.current.volume = v
  }

  const isPlaying = (label: string) => selected === label && playing

  return (
    <div className="ambient-wrap" ref={panelRef} style={{ '--accent': accent } as React.CSSProperties}>
      {/* Main toggle button */}
      <button
        className={`ambient-toggle ${playing ? 'ambient-toggle--active' : ''}`}
        onClick={() => setOpen(o => !o)}
        title="Ambient sounds"
      >
        {playing ? '♫' : '♪'}
      </button>

      {/* Popover */}
      {open && (
        <div className="ambient-panel fade-in">
          <div className="ambient-list">
            {SOUNDS.map(s => (
              <button
                key={s.label}
                className={`ambient-row ${isPlaying(s.label) ? 'ambient-row--active' : ''}`}
                onClick={() => play(s.label, s.file)}
              >
                <span className="ambient-row-icon">{s.icon}</span>
                <span className="ambient-row-label">{s.label}</span>
                <span className="ambient-row-play">
                  {isPlaying(s.label) ? '⏸' : '▶'}
                </span>
              </button>
            ))}
          </div>

          <div className="ambient-vol">
            <span>{volume === 0 ? '🔇' : '🔉'}</span>
            <input
              type="range" min={0} max={1} step={0.01}
              value={volume}
              onChange={handleVolume}
              className="vol-slider"
            />
          </div>
        </div>
      )}
    </div>
  )
}
