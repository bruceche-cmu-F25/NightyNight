import { useEffect, useRef, type ReactNode } from 'react'
import * as THREE from 'three'
import { gsap } from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { SCROLL_ACTS } from './scrollActs'

gsap.registerPlugin(ScrollTrigger)

// ── Atmosphere shader: Fresnel rim + animated aurora color bands ───────────
const atmVert = /* glsl */`
  varying vec3 vNormal;
  varying vec3 vViewDir;
  void main() {
    vec4 mvPos = modelViewMatrix * vec4(position, 1.0);
    vNormal  = normalize(normalMatrix * normal);
    vViewDir = normalize(-mvPos.xyz);
    gl_Position = projectionMatrix * mvPos;
  }
`
const atmFrag = /* glsl */`
  uniform float uTime;
  uniform vec3  uColorA;   // deep blue
  uniform vec3  uColorB;   // aurora teal
  varying vec3  vNormal;
  varying vec3  vViewDir;
  void main() {
    float rim  = pow(1.0 - max(dot(vNormal, vViewDir), 0.0), 2.6);
    float wave = sin(vNormal.y * 5.5 + uTime * 0.38) * 0.5 + 0.5;
    vec3  col  = mix(uColorA, uColorB, wave * 0.55 + rim * 0.45);
    gl_FragColor = vec4(col, rim * 0.95);
  }
`

interface Props {
  children?: ReactNode
  onProgress?: (p: number) => void
}

export default function EarthScene({ children, onProgress }: Props) {
  const scrollRef     = useRef<HTMLDivElement>(null)
  const mountRef      = useRef<HTMLDivElement>(null)
  const onProgressRef = useRef(onProgress)
  useEffect(() => { onProgressRef.current = onProgress }, [onProgress])

  useEffect(() => {
    const scrollEl = scrollRef.current
    const mountEl  = mountRef.current
    if (!scrollEl || !mountEl) return

    // ── Renderer ──────────────────────────────────────────────────
    // try-catch guards against StrictMode's 2nd-mount finding the context already lost
    let renderer: THREE.WebGLRenderer
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true })
    } catch {
      return
    }
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2))
    renderer.setSize(window.innerWidth, window.innerHeight)
    renderer.setClearColor(0x020408)
    mountEl.appendChild(renderer.domElement)

    // ── Scene & Camera ─────────────────────────────────────────────
    const scene  = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(90, window.innerWidth / window.innerHeight, 0.01, 200)

    // Act 1 start: FOV 90° + z=1.12 (just outside atmosphere at r=1.03).
    // Earth's angular span ≈ 126° > 121° horizontal FOV → Earth bleeds past both edges.
    // lookAt y=2.5 tilts camera 65.8° up → horizon sits at ~56% from top, below title.
    camera.position.set(0, 0, 1.12)
    camera.lookAt(0, 2.5, 0)

    // ── Stars ──────────────────────────────────────────────────────
    const starCount = 4000
    const starPos   = new Float32Array(starCount * 3)
    for (let i = 0; i < starCount * 3; i++) starPos[i] = (Math.random() - 0.5) * 120
    const starGeo = new THREE.BufferGeometry()
    starGeo.setAttribute('position', new THREE.BufferAttribute(starPos, 3))
    const starMat = new THREE.PointsMaterial({ color: 0xffffff, size: 0.06, sizeAttenuation: true })
    scene.add(new THREE.Points(starGeo, starMat))

    // ── Textures ───────────────────────────────────────────────────
    const loader = new THREE.TextureLoader()

    // ── Earth group (sphere + clouds + atmosphere rotate together) ─
    const earthGroup = new THREE.Group()
    scene.add(earthGroup)

    // Earth — NASA Black Marble night-lights
    const earthGeo  = new THREE.SphereGeometry(1, 64, 64)
    const earthMat  = new THREE.MeshBasicMaterial({ color: 0x080e1c })
    const earthMesh = new THREE.Mesh(earthGeo, earthMat)
    earthGroup.add(earthMesh)
    loader.load('/textures/earth_night.jpg', tex => {
      tex.colorSpace  = THREE.SRGBColorSpace
      earthMat.map    = tex
      earthMat.color.set(0xffffff)  // reset multiplier so texture shows at full brightness
      earthMat.needsUpdate = true
    })

    // Atmosphere — Fresnel glow with aurora color animation
    const atmGeo = new THREE.SphereGeometry(1.03, 64, 64)
    const atmMat = new THREE.ShaderMaterial({
      vertexShader:   atmVert,
      fragmentShader: atmFrag,
      uniforms: {
        uTime:   { value: 0 },
        uColorA: { value: new THREE.Color(0x163aaa) },  // deep blue, slightly darker
        uColorB: { value: new THREE.Color(0x127755) },  // aurora teal, slightly darker
      },
      transparent: true,
      blending:    THREE.AdditiveBlending,
      depthWrite:  false,
    })
    earthGroup.add(new THREE.Mesh(atmGeo, atmMat))

    // Cloud veil — same radius as atmosphere, additive blending merges with the glow
    const cloudGeo = new THREE.SphereGeometry(1.03, 48, 48)
    const cloudMat = new THREE.MeshBasicMaterial({
      color: 0xb8cce0, transparent: true, opacity: 0.20, depthWrite: false,
      blending: THREE.AdditiveBlending,
    })
    earthGroup.add(new THREE.Mesh(cloudGeo, cloudMat))
    loader.load('/textures/earth_clouds.jpg', tex => {
      cloudMat.alphaMap    = tex
      cloudMat.needsUpdate = true
    })

    // ── Resize ─────────────────────────────────────────────────────
    const onResize = () => {
      const w = window.innerWidth, h = window.innerHeight
      renderer.setSize(w, h)
      camera.aspect = w / h
      camera.updateProjectionMatrix()
    }
    window.addEventListener('resize', onResize)

    // ── Mouse drag (only in Acts 1 & 2) ───────────────────────────
    let isDragging = false, prevX = 0, prevY = 0, scrollProg = 0

    const onPointerDown = (e: PointerEvent) => {
      if (scrollProg > SCROLL_ACTS.approach.start) return
      isDragging = true
      mountEl.style.cursor = 'grabbing'
      prevX = e.clientX; prevY = e.clientY
    }
    const onPointerMove = (e: PointerEvent) => {
      if (!isDragging) return
      const dx = (e.clientX - prevX) * 0.004
      const dy = (e.clientY - prevY) * 0.004
      earthGroup.rotation.y += dx
      earthGroup.rotation.x  = Math.max(-0.45, Math.min(0.45, earthGroup.rotation.x + dy))
      prevX = e.clientX; prevY = e.clientY
    }
    const onPointerUp = () => { isDragging = false; mountEl.style.cursor = 'grab' }
    mountEl.addEventListener('pointerdown', onPointerDown)
    mountEl.addEventListener('pointermove', onPointerMove)
    window.addEventListener('pointerup', onPointerUp)

    // ── Camera targets (set by scroll, lerped in render loop) ──────
    const camTarget  = { z: 1.12, lookY: 2.5, fov: 90 }
    const camCurrent = { z: 1.12, lookY: 2.5, fov: 90 }

    // ── ScrollTrigger — 4-act journey ─────────────────────────────
    //
    //  Act 1  (0.00 – 0.20)  Hero — close, Earth only at bottom of screen
    //  Act 1→2(0.20 – 0.50)  Pull back — Earth rises and becomes whole
    //  Act 2  (0.50 – 0.66)  Hold — full Earth floating in space (extended hold)
    //  Act 2→3(0.66 – 0.82)  Re-approach — zoom back in, clouds thicken
    //  Act 3→4(0.82 – 1.00)  Enter clouds → darkness (blackout delayed)
    //
    //  Camera z:  1.12 → 6.0 → 2.5 → 0.12
    //  LookAt y:  2.5 → 0.0 → 0.0 → 0.0
    //  FOV:      90° → 45° → 45° → 45°

    ScrollTrigger.create({
      trigger: scrollEl,
      start:   'top top',
      end:     'bottom bottom',
      scrub:   1.5,
      snap: {
        snapTo:   SCROLL_ACTS.snapPoints,
        duration: { min: 0.2, max: 0.5 },
        delay:    0.4,
        ease:     'power1.inOut',
      },
      onUpdate(self) {
        const p = self.progress
        scrollProg = p
        onProgressRef.current?.(p)

        if (p <= SCROLL_ACTS.hero.end) {
          camTarget.z     = 1.12
          camTarget.lookY = 2.5
          camTarget.fov   = 90

        } else if (p <= SCROLL_ACTS.pullback.end) {
          const t = (p - SCROLL_ACTS.pullback.start) / (SCROLL_ACTS.pullback.end - SCROLL_ACTS.pullback.start)
          camTarget.z     = gsap.utils.interpolate(1.12, 6.0, t)
          camTarget.lookY = gsap.utils.interpolate(2.5, 0.0, t)
          camTarget.fov   = gsap.utils.interpolate(90, 45, t)

        } else if (p <= SCROLL_ACTS.hold.end) {
          camTarget.z     = 6.0
          camTarget.lookY = 0.0
          camTarget.fov   = 45

        } else if (p <= SCROLL_ACTS.approach.end) {
          const t = (p - SCROLL_ACTS.approach.start) / (SCROLL_ACTS.approach.end - SCROLL_ACTS.approach.start)
          camTarget.z     = gsap.utils.interpolate(6.0, 2.5, t)
          camTarget.lookY = 0.0
          camTarget.fov   = 45

        } else {
          const t = (p - SCROLL_ACTS.enter.start) / (SCROLL_ACTS.enter.end - SCROLL_ACTS.enter.start)
          camTarget.z     = gsap.utils.interpolate(2.5, 0.12, t)
          camTarget.lookY = 0.0
          camTarget.fov   = 45
        }

      },
    })

    // ── Render loop ────────────────────────────────────────────────
    let rafId: number
    const startTime = performance.now()

    const tick = () => {
      rafId = requestAnimationFrame(tick)
      const t = (performance.now() - startTime) / 1000

      // Smooth camera
      camCurrent.z    += (camTarget.z    - camCurrent.z)    * 0.055
      camCurrent.lookY += (camTarget.lookY - camCurrent.lookY) * 0.055
      camCurrent.fov   += (camTarget.fov   - camCurrent.fov)   * 0.055
      camera.position.z = camCurrent.z
      camera.lookAt(0, camCurrent.lookY, 0)
      camera.fov = camCurrent.fov
      camera.updateProjectionMatrix()

      // Auto-rotation slows during re-approach so we land cleanly
      if (!isDragging) {
        const spin = scrollProg > SCROLL_ACTS.approach.start
          ? 0.0014 * Math.max(0, 1 - (scrollProg - SCROLL_ACTS.approach.start) / (SCROLL_ACTS.approach.end - SCROLL_ACTS.approach.start))
          : 0.0014
        earthGroup.rotation.y += spin
      }

      atmMat.uniforms.uTime.value = t
      renderer.render(scene, camera)
    }
    tick()

    return () => {
      cancelAnimationFrame(rafId)
      window.removeEventListener('resize', onResize)
      window.removeEventListener('pointerup', onPointerUp)
      mountEl.removeEventListener('pointerdown', onPointerDown)
      mountEl.removeEventListener('pointermove', onPointerMove)
      ScrollTrigger.getAll().forEach(st => st.kill())
      ;[starGeo, earthGeo, cloudGeo, atmGeo].forEach(g => g.dispose())
      ;[earthMat, cloudMat, atmMat, starMat].forEach(m => m.dispose())
      renderer.forceContextLoss()
      renderer.dispose()
      if (mountEl.contains(renderer.domElement)) mountEl.removeChild(renderer.domElement)
    }
  }, [])

  return (
    <div ref={scrollRef} style={{ height: '700vh' }}>
      <div style={{ position: 'sticky', top: 0, height: '100dvh' }}>
        <div ref={mountRef} style={{ position: 'absolute', inset: 0, cursor: 'grab' }} />
        {children}
      </div>
    </div>
  )
}
