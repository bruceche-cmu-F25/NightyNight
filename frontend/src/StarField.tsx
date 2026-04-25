import { useEffect, useRef } from 'react'
import * as THREE from 'three'
import { Theme } from './theme'

export type BackgroundMode = 'stars' | 'aurora' | 'dreamy'

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

  // ── Dreamy canvas (children mode) ────────────────────────────────────────
  useEffect(() => {
    if (mode !== 'dreamy') return
    const canvas = canvasRef.current!
    const ctx    = canvas.getContext('2d')!

    const resize = () => { canvas.width = window.innerWidth; canvas.height = window.innerHeight }
    resize()
    window.addEventListener('resize', resize)

    const STAR_COLORS = ['#ffe566', '#ffb3d1', '#c9b3ff', '#b3e8ff', '#b3ffd6']
    const COUNT = 90

    interface DreamyStar {
      x: number; y: number
      vx: number; vy: number
      radius: number
      color: string
      opacity: number
      opacityDelta: number
      sparkle: boolean
    }

    const stars: DreamyStar[] = Array.from({ length: COUNT }, () => ({
      x:            Math.random() * window.innerWidth,
      y:            Math.random() * window.innerHeight,
      vx:           (Math.random() - 0.5) * 0.08,
      vy:           (Math.random() - 0.5) * 0.08,
      radius:       Math.random() * 2.2 + 0.8,
      color:        STAR_COLORS[Math.floor(Math.random() * STAR_COLORS.length)],
      opacity:      Math.random(),
      opacityDelta: (Math.random() * 0.006 + 0.002) * (Math.random() < 0.5 ? 1 : -1),
      sparkle:      Math.random() < 0.2,
    }))

    const drawMoon = () => {
      const cx = 110
      const cy = 90
      const r  = 46
      // glow
      const glow = ctx.createRadialGradient(cx, cy, r * 0.5, cx, cy, r * 2.2)
      glow.addColorStop(0, 'rgba(255, 245, 180, 0.18)')
      glow.addColorStop(1, 'rgba(255, 245, 180, 0)')
      ctx.beginPath()
      ctx.arc(cx, cy, r * 2.2, 0, Math.PI * 2)
      ctx.fillStyle = glow
      ctx.fill()
      // moon disc
      ctx.beginPath()
      ctx.arc(cx, cy, r, 0, Math.PI * 2)
      ctx.fillStyle = '#fff8c0'
      ctx.fill()
      // crescent shadow
      ctx.beginPath()
      ctx.arc(cx - r * 0.42, cy - r * 0.08, r * 0.88, 0, Math.PI * 2)
      ctx.fillStyle = '#1a1235'
      ctx.fill()
    }

    const drawSparkle = (x: number, y: number, r: number, color: string, alpha: number) => {
      ctx.save()
      ctx.globalAlpha = alpha * 0.9
      ctx.strokeStyle = color
      ctx.lineWidth = r * 0.6
      ctx.lineCap = 'round'
      const arm = r * 2.8
      ctx.beginPath(); ctx.moveTo(x - arm, y); ctx.lineTo(x + arm, y); ctx.stroke()
      ctx.beginPath(); ctx.moveTo(x, y - arm); ctx.lineTo(x, y + arm); ctx.stroke()
      ctx.globalAlpha = alpha * 0.45
      const diag = arm * 0.65
      ctx.beginPath(); ctx.moveTo(x - diag, y - diag); ctx.lineTo(x + diag, y + diag); ctx.stroke()
      ctx.beginPath(); ctx.moveTo(x + diag, y - diag); ctx.lineTo(x - diag, y + diag); ctx.stroke()
      ctx.restore()
    }

    const draw = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      drawMoon()
      for (const s of stars) {
        s.x += s.vx; s.y += s.vy
        if (s.x < 0) s.x = canvas.width
        if (s.x > canvas.width)  s.x = 0
        if (s.y < 0) s.y = canvas.height
        if (s.y > canvas.height) s.y = 0
        s.opacity += s.opacityDelta
        if (s.opacity >= 1 || s.opacity <= 0.05) s.opacityDelta *= -1
        s.opacity = Math.max(0.05, Math.min(1, s.opacity))

        if (s.sparkle) {
          drawSparkle(s.x, s.y, s.radius, s.color, s.opacity)
        } else {
          // soft glow
          const grad = ctx.createRadialGradient(s.x, s.y, 0, s.x, s.y, s.radius * 3)
          grad.addColorStop(0, s.color)
          grad.addColorStop(1, 'transparent')
          ctx.beginPath()
          ctx.arc(s.x, s.y, s.radius * 3, 0, Math.PI * 2)
          ctx.globalAlpha = s.opacity * 0.3
          ctx.fillStyle = grad
          ctx.fill()
          // core dot
          ctx.beginPath()
          ctx.arc(s.x, s.y, s.radius, 0, Math.PI * 2)
          ctx.globalAlpha = s.opacity * 0.9
          ctx.fillStyle = s.color
          ctx.fill()
        }
      }
      ctx.globalAlpha = 1
      animId.current = requestAnimationFrame(draw)
    }

    animId.current = requestAnimationFrame(draw)
    return () => { cancelAnimationFrame(animId.current); window.removeEventListener('resize', resize) }
  }, [mode])

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
      {/* Star / dreamy canvas */}
      <canvas
        ref={canvasRef}
        style={{
          display:  (mode === 'stars' || mode === 'dreamy') ? 'block' : 'none',
          position: 'fixed', inset: 0, pointerEvents: 'none', zIndex: 0,
        }}
      />
    </>
  )
}
