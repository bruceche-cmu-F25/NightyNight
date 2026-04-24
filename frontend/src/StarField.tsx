import { useEffect, useRef } from 'react'
import * as THREE from 'three'
import { Theme } from './theme'

export type BackgroundMode = 'stars' | 'aurora'

interface Particle {
  x: number; y: number
  vx: number; vy: number
  radius: number
  opacity: number
  opacityDelta: number
}

interface Props {
  theme: Theme
  mode: BackgroundMode
}

export default function StarField({ theme, mode }: Props) {
  const canvasRef  = useRef<HTMLCanvasElement>(null)
  const vantaRef   = useRef<HTMLDivElement>(null)
  const vantaFx    = useRef<any>(null)
  const themeRef   = useRef(theme)
  const modeRef    = useRef(mode)
  const animId     = useRef(0)

  themeRef.current = theme
  modeRef.current  = mode

  // ── Vanta FOG (aurora mode) ───────────────────────────────────────────────
  useEffect(() => {
    if (mode !== 'aurora') {
      // destroy if switching away
      if (vantaFx.current) { vantaFx.current.destroy(); vantaFx.current = null }
      return
    }
    if (!vantaRef.current) return

    import('vanta/dist/vanta.fog.min').then(mod => {
      if (vantaFx.current) vantaFx.current.destroy()
      vantaFx.current = mod.default({
        el:             vantaRef.current,
        THREE,
        highlightColor: 0x4a9a4a,  // deeper green
        midtoneColor:   0x005c3a,  // darker green
        lowlightColor:  0xaa00aa,  // brighter magenta
        baseColor:      0x000d28,  // slightly brighter dark blue
        blurFactor:     0.75,
        speed:          0.9,
        zoom:           0.5,
      })
    })

    return () => { if (vantaFx.current) { vantaFx.current.destroy(); vantaFx.current = null } }
  }, [mode, theme.accentColor, theme.particleColor])

  // ── Canvas stars ──────────────────────────────────────────────────────────
  useEffect(() => {
    if (mode !== 'stars') return
    const canvas = canvasRef.current!
    const ctx    = canvas.getContext('2d')!
    const COUNT  = 120

    const resize = () => { canvas.width = window.innerWidth; canvas.height = window.innerHeight }
    resize()
    window.addEventListener('resize', resize)

    const particles: Particle[] = Array.from({ length: COUNT }, () => ({
      x:            Math.random() * canvas.width,
      y:            Math.random() * canvas.height,
      vx:           (Math.random() - 0.5) * 0.12,
      vy:           (Math.random() - 0.5) * 0.12,
      radius:       Math.random() * 1.4 + 0.3,
      opacity:      Math.random(),
      opacityDelta: (Math.random() * 0.004 + 0.001) * (Math.random() < 0.5 ? 1 : -1),
    }))

    const draw = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      const color = themeRef.current.particleColor
      for (const p of particles) {
        p.x += p.vx; p.y += p.vy
        if (p.x < 0) p.x = canvas.width
        if (p.x > canvas.width)  p.x = 0
        if (p.y < 0) p.y = canvas.height
        if (p.y > canvas.height) p.y = 0
        p.opacity += p.opacityDelta
        if (p.opacity >= 1 || p.opacity <= 0.05) p.opacityDelta *= -1
        p.opacity = Math.max(0.05, Math.min(1, p.opacity))
        ctx.beginPath()
        ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2)
        ctx.fillStyle = color
        ctx.globalAlpha = p.opacity * 0.8
        ctx.fill()
      }
      ctx.globalAlpha = 1
      animId.current = requestAnimationFrame(draw)
    }

    animId.current = requestAnimationFrame(draw)
    return () => { cancelAnimationFrame(animId.current); window.removeEventListener('resize', resize) }
  }, [mode])

  return (
    <>
      {/* Vanta target div */}
      <div
        ref={vantaRef}
        style={{
          display:  mode === 'aurora' ? 'block' : 'none',
          position: 'fixed', inset: 0, zIndex: 0,
        }}
      />
      {/* Star canvas */}
      <canvas
        ref={canvasRef}
        style={{
          display:  mode === 'stars' ? 'block' : 'none',
          position: 'fixed', inset: 0, pointerEvents: 'none', zIndex: 0,
        }}
      />
    </>
  )
}
