import { useEffect, useRef, useState } from 'react'

const SOUNDS = [
  { label: 'Rain',   icon: '🌧', category: 'rain'   },
  { label: 'Ocean',  icon: '🌊', category: 'ocean'  },
  { label: 'Fire',   icon: '🔥', category: 'fire'   },
  { label: 'Woods',  icon: '🌲', category: 'woods'  },
  { label: 'Cosmos', icon: '🌌', category: 'cosmos' },
]

interface Props {
  accent: string
  autoPlay?: string | null  // ambient category to auto-start (only if nothing playing yet)
}

export default function AmbientPlayer({ accent, autoPlay }: Props) {
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

  // auto-start when generation begins (only if user hasn't manually picked a sound)
  useEffect(() => {
    if (!autoPlay || selected || !audioRef.current) return
    const sound = SOUNDS.find(s => s.category === autoPlay)
    if (!sound) return
    const a = audioRef.current
    a.src = `/ambient/${sound.category}`
    a.volume = volume
    a.play().then(() => { setPlaying(true); setSelected(sound.label) }).catch(() => {})
  }, [autoPlay])

  // close panel on outside click
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const play = (label: string, category: string) => {
    const a = audioRef.current!
    if (selected === label) {
      // toggle play/pause
      if (playing) { a.pause(); setPlaying(false) }
      else         { a.play(); setPlaying(true) }
    } else {
      // fresh URL each time → backend picks a random file from the category
      a.src = `/ambient/${category}`
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
                onClick={() => play(s.label, s.category)}
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
