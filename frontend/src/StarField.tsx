import { useEffect, useRef } from 'react'
import * as THREE from 'three'

export type BackgroundMode = 'stars' | 'aurora' | 'dreamy' | 'galaxy'

interface Props {
  mode: BackgroundMode
}

export default function StarField({ mode }: Props) {
  const canvasRef  = useRef<HTMLCanvasElement>(null)
  const vantaRef   = useRef<HTMLDivElement>(null)
  const vantaFx    = useRef<any>(null)
  const animId     = useRef(0)

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
  }, [mode])

  // ── Dreamy canvas (children mode) ────────────────────────────────────────
  useEffect(() => {
    if (mode !== 'dreamy') return
    const canvas = canvasRef.current!
    const ctx    = canvas.getContext('2d')!

    const STAR_COLORS = ['#ffe566', '#ffb3d1', '#c9b3ff', '#b3e8ff', '#b3ffd6']
    const COUNT = window.innerWidth < 768 ? 50 : 90

    canvas.width  = window.innerWidth
    canvas.height = window.innerHeight

    const onResize = () => {
      canvas.width  = window.innerWidth
      canvas.height = window.innerHeight
    }
    window.addEventListener('resize', onResize, { passive: true })

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
      x:            Math.random() * canvas.width,
      y:            Math.random() * canvas.height,
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
    return () => { cancelAnimationFrame(animId.current); window.removeEventListener('resize', onResize) }
  }, [mode])

  // ── Galaxy canvas (galaxy-shaped, dense core, comets) ────────────────────
  useEffect(() => {
    if (mode !== 'galaxy') return
    const canvas = canvasRef.current!
    const ctx    = canvas.getContext('2d')!

    canvas.width  = window.innerWidth
    canvas.height = window.innerHeight

    const gauss = () => {
      let u = 0, v = 0
      while (!u) u = Math.random()
      while (!v) v = Math.random()
      return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v)
    }

    const CORE_COLORS = ['#fff8e0', '#ffe8a0', '#ffd080', '#e0f0ff', '#c0d8ff', '#ffb8b8']
    const EDGE_COLORS = ['#ffffff', '#e8eeff', '#f0f8ff']
    const TILT = Math.PI * 0.22
    const STAR_COUNT = window.innerWidth < 768 ? 150 : 300

    interface GalaxyStar {
      x: number; y: number; r: number; color: string
      opacity: number; delta: number; isCore: boolean
    }

    const makeStars = (): GalaxyStar[] =>
      Array.from({ length: STAR_COUNT }, () => {
        const gx = gauss() * canvas.width  * 0.28
        const gy = gauss() * canvas.height * 0.16
        const rx = gx * Math.cos(TILT) - gy * Math.sin(TILT) + canvas.width  / 2
        const ry = gx * Math.sin(TILT) + gy * Math.cos(TILT) + canvas.height / 2
        const dx = (rx - canvas.width  / 2) / canvas.width
        const dy = (ry - canvas.height / 2) / canvas.height
        const isCore = Math.sqrt(dx * dx + dy * dy) < 0.12
        return {
          x: rx, y: ry,
          r: isCore ? Math.random() * 1.9 + 0.7 : Math.random() * 1.1 + 0.2,
          color: isCore
            ? CORE_COLORS[Math.floor(Math.random() * CORE_COLORS.length)]
            : EDGE_COLORS[Math.floor(Math.random() * EDGE_COLORS.length)],
          opacity: Math.random() * 0.6 + 0.3,
          delta: (Math.random() * 0.004 + 0.001) * (Math.random() < 0.5 ? 1 : -1),
          isCore,
        }
      })

    let stars = makeStars()
    let galaxyResizeTimer: ReturnType<typeof setTimeout>
    const onGalaxyResize = () => {
      canvas.width  = window.innerWidth
      canvas.height = window.innerHeight
      clearTimeout(galaxyResizeTimer)
      galaxyResizeTimer = setTimeout(() => { stars = makeStars() }, 150)
    }
    window.addEventListener('resize', onGalaxyResize, { passive: true })

    interface Comet { x: number; y: number; vx: number; vy: number; len: number; opacity: number; active: boolean }
    const spawnComet = (): Comet => {
      const speed = Math.random() * 2.5 + 1.5
      const angle = Math.random() * 0.3 + 0.15
      return {
        x: Math.random() * canvas.width * 0.6,
        y: Math.random() * canvas.height * 0.35,
        vx: speed * Math.cos(angle),
        vy: speed * Math.sin(angle),
        len: Math.random() * 200 + 130,
        opacity: 0.85,
        active: true,
      }
    }
    const comets: Comet[] = [{ ...spawnComet(), active: false }, { ...spawnComet(), active: false }]
    let cometTimer = 0

    const draw = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height)

      // Soft central core glow
      const coreGrad = ctx.createRadialGradient(
        canvas.width / 2, canvas.height / 2, 0,
        canvas.width / 2, canvas.height / 2, canvas.width * 0.22
      )
      coreGrad.addColorStop(0,   'rgba(200, 170, 100, 0.07)')
      coreGrad.addColorStop(0.4, 'rgba(80, 110, 200, 0.04)')
      coreGrad.addColorStop(1,   'rgba(0, 0, 0, 0)')
      ctx.fillStyle = coreGrad
      ctx.fillRect(0, 0, canvas.width, canvas.height)

      // Stars
      for (const s of stars) {
        s.opacity += s.delta
        if (s.opacity > 0.95 || s.opacity < 0.15) s.delta *= -1
        if (s.isCore && s.r > 1.2) {
          const glow = ctx.createRadialGradient(s.x, s.y, 0, s.x, s.y, s.r * 3.5)
          glow.addColorStop(0, s.color); glow.addColorStop(1, 'transparent')
          ctx.beginPath(); ctx.arc(s.x, s.y, s.r * 3.5, 0, Math.PI * 2)
          ctx.globalAlpha = s.opacity * 0.25; ctx.fillStyle = glow; ctx.fill()
        }
        ctx.beginPath(); ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2)
        ctx.globalAlpha = s.opacity; ctx.fillStyle = s.color; ctx.fill()
      }

      // Comets
      cometTimer++
      if (cometTimer > 200) {
        cometTimer = 0
        const dead = comets.find(c => !c.active)
        if (dead) Object.assign(dead, spawnComet())
      }
      for (const c of comets) {
        if (!c.active) continue
        c.x += c.vx; c.y += c.vy
        c.opacity -= 0.004
        if (c.opacity <= 0 || c.x > canvas.width + 100 || c.y > canvas.height + 100) {
          c.active = false; continue
        }
        const mag = Math.sqrt(c.vx * c.vx + c.vy * c.vy)
        const tx = c.x - (c.vx / mag) * c.len
        const ty = c.y - (c.vy / mag) * c.len
        const tailGrad = ctx.createLinearGradient(c.x, c.y, tx, ty)
        tailGrad.addColorStop(0,    `rgba(230, 240, 255, ${c.opacity})`)
        tailGrad.addColorStop(0.25, `rgba(180, 210, 255, ${c.opacity * 0.55})`)
        tailGrad.addColorStop(1,    'rgba(160, 190, 255, 0)')
        ctx.beginPath(); ctx.moveTo(c.x, c.y); ctx.lineTo(tx, ty)
        ctx.strokeStyle = tailGrad; ctx.lineWidth = 1.6; ctx.globalAlpha = 1; ctx.stroke()
        const headGrad = ctx.createRadialGradient(c.x, c.y, 0, c.x, c.y, 7)
        headGrad.addColorStop(0, `rgba(255, 255, 255, ${c.opacity})`); headGrad.addColorStop(1, 'transparent')
        ctx.beginPath(); ctx.arc(c.x, c.y, 7, 0, Math.PI * 2)
        ctx.fillStyle = headGrad; ctx.globalAlpha = 1; ctx.fill()
      }

      ctx.globalAlpha = 1
      animId.current = requestAnimationFrame(draw)
    }

    animId.current = requestAnimationFrame(draw)
    return () => { cancelAnimationFrame(animId.current); clearTimeout(galaxyResizeTimer); window.removeEventListener('resize', onGalaxyResize) }
  }, [mode])

  // ── Canvas stars (3-layer depth, sprite cache, 30 fps cap) ──────────────
  useEffect(() => {
    if (mode !== 'stars') return
    const canvas = canvasRef.current!
    const ctx    = canvas.getContext('2d')!

    const TINTS = ['#ffffff', '#c1e1fa', '#92b4f1', '#f2cca4', '#eccece', '#f0d0e0']
    const rand  = (lo: number, hi: number) => Math.random() * (hi - lo) + lo
    const pick  = () => TINTS[Math.floor(Math.random() * TINTS.length)]

    // Pre-render a glow halo onto a tiny offscreen canvas once per star.
    // Appending '00' to the hex colour gives a colour-correct transparent stop
    // so there's no dark halo around coloured stars.
    const makeSprite = (r: number, hex: string): HTMLCanvasElement => {
      const glowR  = Math.ceil(r * 3.5)
      const d      = glowR * 2
      const oc     = document.createElement('canvas')
      oc.width     = d
      oc.height    = d
      const oc2    = oc.getContext('2d')!
      const g      = oc2.createRadialGradient(glowR, glowR, 0, glowR, glowR, glowR)
      g.addColorStop(0, hex)
      g.addColorStop(1, hex + '00')
      oc2.beginPath(); oc2.arc(glowR, glowR, glowR, 0, Math.PI * 2)
      oc2.fillStyle = g; oc2.fill()
      return oc
    }

    interface Star {
      x: number; y: number; vx: number; vy: number
      r: number; color: string
      opacity: number; delta: number
      sprite: HTMLCanvasElement | null
      glowR: number
    }

    const makeStar = (
      w: number, h: number,
      rLo: number, rHi: number,
      speed: number,
      glow: boolean,
    ): Star => {
      const r = rand(rLo, rHi); const color = pick()
      return {
        x: Math.random() * w, y: Math.random() * h,
        vx: (Math.random() - 0.5) * 0.12 * speed,
        vy: (Math.random() - 0.5) * 0.12 * speed,
        r, color,
        opacity: Math.random(),
        delta: rand(0.001, 0.005) * (Math.random() < 0.5 ? 1 : -1),
        sprite: glow ? makeSprite(r, color) : null,
        glowR:  glow ? Math.ceil(r * 3.5) : 0,
      }
    }

    // Three depth layers drawn back-to-front: far stars behind, near in front.
    // Desktop: 150 far + 110 mid + 40 near = 300. Mobile: 90+55+20 = 165.
    const mobile  = window.innerWidth < 768
    const makeAll = (w: number, h: number): Star[] => [
      ...Array.from({ length: mobile ? 90  : 150 }, () => makeStar(w, h, 0.3, 0.9, 0.25, false)),
      ...Array.from({ length: mobile ? 55  : 110 }, () => makeStar(w, h, 1.0, 1.6, 0.55, true)),
      ...Array.from({ length: mobile ? 20  : 40  }, () => makeStar(w, h, 1.8, 2.8, 1.0,  true)),
    ]

    canvas.width  = window.innerWidth
    canvas.height = window.innerHeight
    let stars     = makeAll(canvas.width, canvas.height)

    let resizeTimer: ReturnType<typeof setTimeout>
    const resize = () => {
      canvas.width  = window.innerWidth
      canvas.height = window.innerHeight
      clearTimeout(resizeTimer)
      resizeTimer = setTimeout(() => { stars = makeAll(canvas.width, canvas.height) }, 150)
    }
    window.addEventListener('resize', resize, { passive: true })

    let lastT    = 0
    const FRAME_MS = 1000 / 30   // cap at 30 fps

    const draw = (t: number) => {
      animId.current = requestAnimationFrame(draw)
      if (t - lastT < FRAME_MS) return
      lastT = t

      ctx.clearRect(0, 0, canvas.width, canvas.height)
      for (const s of stars) {
        s.x += s.vx; s.y += s.vy
        if (s.x < 0) s.x = canvas.width
        if (s.x > canvas.width)  s.x = 0
        if (s.y < 0) s.y = canvas.height
        if (s.y > canvas.height) s.y = 0

        s.opacity += s.delta
        if (s.opacity >= 1 || s.opacity <= 0.05) s.delta *= -1
        s.opacity = Math.max(0.05, Math.min(1, s.opacity))

        if (s.sprite) {
          ctx.globalAlpha = s.opacity * 0.32
          ctx.drawImage(s.sprite, s.x - s.glowR, s.y - s.glowR)
        }
        ctx.globalAlpha = s.opacity * (s.sprite ? 0.92 : 0.72)
        ctx.fillStyle   = s.color
        ctx.beginPath(); ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2); ctx.fill()
      }
      ctx.globalAlpha = 1
    }

    animId.current = requestAnimationFrame(draw)
    return () => {
      cancelAnimationFrame(animId.current)
      clearTimeout(resizeTimer)
      window.removeEventListener('resize', resize)
    }
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
      {/* Star / dreamy / galaxy / stellar canvas */}
      <canvas
        ref={canvasRef}
        style={{
          display:  mode !== 'aurora' ? 'block' : 'none',
          position: 'fixed', inset: 0, pointerEvents: 'none', zIndex: 0,
        }}
      />
    </>
  )
}
