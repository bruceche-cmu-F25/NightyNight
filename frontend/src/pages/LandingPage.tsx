import { useCallback, useRef } from 'react'
import { Link, Navigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import EarthScene from '../EarthScene'

const ACCENT = '#7fa8c8'

// ── Text overlay layers ────────────────────────────────────────────────────
// All positioned absolute inside the sticky 100dvh frame.
// onProgress updates opacity imperatively — no React state → no re-renders.

function HeroOverlay({ heroRef }: { heroRef: React.RefObject<HTMLDivElement> }) {
  return (
    <div
      ref={heroRef}
      style={{
        position: 'absolute',
        inset: 0,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        textAlign: 'center',
        padding: '2rem 1.5rem',
        gap: '0',
        zIndex: 1,
        pointerEvents: 'none',   // mouse events fall through to Three.js
      }}
    >
      <p style={{
        fontFamily: 'Inter, sans-serif',
        fontSize: '0.7rem',
        letterSpacing: '0.2em',
        textTransform: 'uppercase',
        color: 'rgba(127,168,200,0.5)',
        marginBottom: '1.5rem',
      }}>
        · Bedtime stories, made by AI ·
      </p>

      <h1 style={{
        fontFamily: "'Lora', serif",
        fontWeight: 400,
        fontSize: 'clamp(3.5rem, 10vw, 6.5rem)',
        lineHeight: 1.05,
        letterSpacing: '0.03em',
        color: '#f0f0ff',
        textShadow: '0 0 80px rgba(180,180,255,0.28)',
        margin: 0,
        marginBottom: '1.25rem',
      }}>
        NightyNight
      </h1>

      <p style={{
        fontFamily: "'Lora', serif",
        fontStyle: 'italic',
        fontWeight: 400,
        fontSize: 'clamp(1rem, 2.8vw, 1.3rem)',
        color: 'rgba(220,220,240,0.55)',
        maxWidth: '480px',
        lineHeight: 1.65,
        margin: 0,
        marginBottom: '2.5rem',
      }}>
        Sleep through the wonders of science
      </p>

      {/* CTAs need pointer events restored */}
      <div style={{ display: 'flex', gap: '0.8rem', flexWrap: 'wrap', justifyContent: 'center', pointerEvents: 'auto' }}>
        <Link
          to="/register"
          style={{
            background: ACCENT,
            color: '#07111e',
            borderRadius: '999px',
            padding: '0.85rem 2.6rem',
            fontSize: '0.88rem',
            fontWeight: 500,
            letterSpacing: '0.06em',
            textDecoration: 'none',
            fontFamily: 'Inter, sans-serif',
          }}
        >
          Start for free
        </Link>
        <Link
          to="/login"
          style={{
            background: 'transparent',
            color: ACCENT,
            border: `1px solid rgba(127,168,200,0.45)`,
            borderRadius: '999px',
            padding: '0.85rem 2.6rem',
            fontSize: '0.88rem',
            fontWeight: 400,
            letterSpacing: '0.06em',
            textDecoration: 'none',
            fontFamily: 'Inter, sans-serif',
          }}
        >
          Sign in
        </Link>
      </div>

      {/* Scroll hint */}
      <p style={{
        position: 'absolute',
        bottom: '2.5rem',
        fontFamily: 'Inter, sans-serif',
        fontSize: '0.68rem',
        letterSpacing: '0.18em',
        color: 'rgba(127,168,200,0.35)',
        textTransform: 'uppercase',
      }}>
        Scroll to explore
      </p>
    </div>
  )
}

// ── Mid-journey caption (appears during approach) ──────────────────────────
function ApproachOverlay({ midRef }: { midRef: React.RefObject<HTMLDivElement> }) {
  const tag: React.CSSProperties = {
    fontFamily: 'Inter, sans-serif',
    fontSize: '0.65rem',
    letterSpacing: '0.14em',
    textTransform: 'uppercase',
    fontWeight: 300,
    color: 'rgba(170,205,230,0.36)',
    margin: 0,
  }
  return (
    <div
      ref={midRef}
      style={{
        position: 'absolute',
        inset: 0,
        opacity: 0,
        pointerEvents: 'none',
        zIndex: 1,
      }}
    >
      {/* Centre caption */}
      <p style={{
        position: 'absolute',
        bottom: '12%',
        left: 0,
        right: 0,
        textAlign: 'center',
        fontFamily: "'Lora', serif",
        fontStyle: 'italic',
        fontSize: 'clamp(1rem, 2.5vw, 1.4rem)',
        color: 'rgba(200,215,240,0.70)',
        margin: 0,
      }}>
        Every night, a universe of stories
      </p>

      {/* Left column */}
      <div style={{ position: 'absolute', left: '6%', top: '18%', bottom: '22%', display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
        {['Evolution', 'Anthropology', 'Cosmology', 'Physics'].map(s => (
          <p key={s} style={tag}>{s}</p>
        ))}
      </div>

      {/* Right column */}
      <div style={{ position: 'absolute', right: '6%', top: '18%', bottom: '22%', display: 'flex', flexDirection: 'column', justifyContent: 'space-between', alignItems: 'flex-end' }}>
        {['Biology', 'Chemistry', 'History', 'Geology'].map(s => (
          <p key={s} style={tag}>{s}</p>
        ))}
      </div>
    </div>
  )
}

// ── Surface caption (appears near the end of the scroll journey) ───────────
function SurfaceOverlay({ surfaceRef }: { surfaceRef: React.RefObject<HTMLDivElement> }) {
  return (
    <div
      ref={surfaceRef}
      style={{
        position: 'absolute',
        top: '50%',
        left: 0,
        right: 0,
        transform: 'translateY(-50%)',
        textAlign: 'center',
        opacity: 0,
        pointerEvents: 'none',
        zIndex: 6,
      }}
    >
      <p style={{
        fontFamily: "'Lora', serif",
        fontWeight: 400,
        fontSize: 'clamp(1.4rem, 3vw, 2rem)',
        color: '#f0f0ff',
        margin: 0,
        marginBottom: '0.5rem',
      }}>
        Your story is waiting.
      </p>
      <p style={{
        fontFamily: "'Lora', serif",
        fontStyle: 'italic',
        fontSize: '0.95rem',
        color: 'rgba(200,200,220,0.38)',
        margin: 0,
      }}>
        Let the night bring you to peace.
      </p>
    </div>
  )
}

// ── Product intro section ──────────────────────────────────────────────────
const WARM = '#c4a55a'

const FEATURES = [
  {
    icon: '✦',
    title: 'Science you love',
    body: 'From cosmology to evolution, every story draws on real science — woven into a narrative that carries you gently toward sleep.',
  },
  {
    icon: '◎',
    title: 'Your pace, your voice',
    body: 'Choose a narrator, set the length, pick your audience — a quiet tale for a child or a deep-dive for a curious adult.',
  },
  {
    icon: '◐',
    title: 'Never the same twice',
    body: 'Every story is freshly generated for tonight. Press play, let your mind wander, and wake up somewhere new.',
  },
]

const STEPS = [
  'Choose a topic — or let us surprise you',
  'Set the mood: length, voice, and audience',
  'Listen. Sleep. Dream.',
]

function IntroSection() {
  return (
    <section style={{
      background: 'linear-gradient(180deg, #020408 0%, #020408 12%, #100d09 30%, #0c0818 75%, #080614 100%)',
      color: '#e8e8f0',
      overflow: 'hidden',
    }}>

      {/* ── Hero statement ── */}
      <div style={{
        minHeight: '100dvh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        textAlign: 'center',
        padding: '8rem 2rem',
        gap: '1.6rem',
        position: 'relative',
      }}>
        <div style={{
          position: 'absolute',
          top: '38%', left: '50%',
          transform: 'translate(-50%, -50%)',
          width: '700px', height: '340px',
          background: 'radial-gradient(ellipse, rgba(180,120,45,0.07) 0%, transparent 70%)',
          pointerEvents: 'none',
        }} />

        <p style={{
          fontFamily: 'Inter, sans-serif',
          fontSize: '0.68rem',
          letterSpacing: '0.2em',
          textTransform: 'uppercase',
          color: `rgba(196,165,90,0.48)`,
          margin: 0,
        }}>
          What is NightyNight?
        </p>

        <h2 style={{
          fontFamily: "'Lora', serif",
          fontWeight: 400,
          fontSize: 'clamp(2rem, 5vw, 3.5rem)',
          lineHeight: 1.15,
          letterSpacing: '0.02em',
          color: '#f4f0e6',
          maxWidth: '680px',
          margin: 0,
        }}>
          Science, woven into sleep.
        </h2>

        <p style={{
          fontFamily: 'Inter, sans-serif',
          fontWeight: 300,
          fontSize: 'clamp(0.92rem, 2vw, 1.02rem)',
          color: 'rgba(210,205,192,0.52)',
          maxWidth: '480px',
          lineHeight: 1.9,
          margin: 0,
        }}>
          NightyNight turns the wonders of the universe into gentle audio stories —
          black holes, ancient civilizations, the chemistry of life —
          narrated softly as you drift off.
        </p>

        <div style={{ display: 'flex', gap: '0.8rem', marginTop: '0.5rem', flexWrap: 'wrap', justifyContent: 'center' }}>
          <Link to="/register" style={{
            background: WARM,
            color: '#08060e',
            borderRadius: '999px',
            padding: '0.85rem 2.6rem',
            fontSize: '0.88rem',
            fontWeight: 500,
            letterSpacing: '0.06em',
            textDecoration: 'none',
            fontFamily: 'Inter, sans-serif',
          }}>
            Start tonight — it's free
          </Link>
          <Link to="/login" style={{
            background: 'transparent',
            color: WARM,
            border: `1px solid rgba(196,165,90,0.32)`,
            borderRadius: '999px',
            padding: '0.85rem 2.6rem',
            fontSize: '0.88rem',
            fontWeight: 400,
            letterSpacing: '0.06em',
            textDecoration: 'none',
            fontFamily: 'Inter, sans-serif',
          }}>
            Sign in
          </Link>
        </div>
      </div>

      {/* ── Feature cards ── */}
      <div style={{
        padding: '0 2rem 7rem',
        maxWidth: '960px',
        margin: '0 auto',
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
        gap: '1.25rem',
      }}>
        {FEATURES.map(f => (
          <div key={f.title} style={{
            background: 'rgba(255,255,255,0.022)',
            border: '1px solid rgba(255,255,255,0.055)',
            borderRadius: '18px',
            padding: '2rem 1.75rem',
            display: 'flex',
            flexDirection: 'column',
            gap: '1rem',
          }}>
            <span style={{ fontSize: '1rem', color: WARM, opacity: 0.65 }}>{f.icon}</span>
            <h3 style={{
              fontFamily: "'Lora', serif",
              fontWeight: 400,
              fontSize: '1.05rem',
              color: '#f0ece0',
              margin: 0,
            }}>
              {f.title}
            </h3>
            <p style={{
              fontFamily: 'Inter, sans-serif',
              fontWeight: 300,
              fontSize: '0.87rem',
              color: 'rgba(200,195,182,0.52)',
              lineHeight: 1.85,
              margin: 0,
            }}>
              {f.body}
            </p>
          </div>
        ))}
      </div>

      {/* ── How it works ── */}
      <div style={{
        maxWidth: '580px',
        margin: '0 auto',
        padding: '0 2rem 9rem 3.5rem',
        borderLeft: '1px solid rgba(255,255,255,0.055)',
      }}>
        <p style={{
          fontFamily: 'Inter, sans-serif',
          fontSize: '0.68rem',
          letterSpacing: '0.2em',
          textTransform: 'uppercase',
          color: `rgba(196,165,90,0.42)`,
          margin: '0 0 3rem 0',
        }}>
          How it works
        </p>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '2.4rem' }}>
          {STEPS.map((step, i) => (
            <div key={i} style={{ display: 'flex', gap: '2rem', alignItems: 'flex-start' }}>
              <span style={{
                fontFamily: 'Inter, sans-serif',
                fontSize: '0.62rem',
                letterSpacing: '0.1em',
                color: `rgba(196,165,90,0.38)`,
                fontWeight: 300,
                paddingTop: '0.2rem',
                minWidth: '1.8rem',
              }}>
                {String(i + 1).padStart(2, '0')}
              </span>
              <p style={{
                fontFamily: "'Lora', serif",
                fontStyle: 'italic',
                fontSize: '1.05rem',
                color: 'rgba(228,222,210,0.68)',
                margin: 0,
                lineHeight: 1.65,
              }}>
                {step}
              </p>
            </div>
          ))}
        </div>
      </div>

      {/* ── Footer ── */}
      <p style={{
        fontFamily: 'Inter, sans-serif',
        fontSize: '0.7rem',
        color: 'rgba(180,175,160,0.12)',
        textAlign: 'center',
        padding: '0 2rem 4rem',
        letterSpacing: '0.05em',
      }}>
        NightyNight · {new Date().getFullYear()}
      </p>
    </section>
  )
}

// ── Main page ──────────────────────────────────────────────────────────────
export default function LandingPage() {
  const { accessToken, loading } = useAuth()

  const heroRef     = useRef<HTMLDivElement>(null)
  const midRef      = useRef<HTMLDivElement>(null)
  const surfaceRef  = useRef<HTMLDivElement>(null)
  const blackoutRef = useRef<HTMLDivElement>(null)

  // Imperatively update overlay opacity — no React state → no re-renders per frame
  const handleProgress = useCallback((p: number) => {
    if (heroRef.current) {
      // Act 1: hero text visible, fades as camera starts pulling back
      const op = p < 0.12 ? 1 : Math.max(0, 1 - (p - 0.12) / 0.08)
      heroRef.current.style.opacity = String(op)
    }
    if (midRef.current) {
      // Act 2: full Earth in space — "Every night, a universe of stories"
      const fadeIn  = Math.min(Math.max((p - 0.42) / 0.08, 0), 1)
      const fadeOut = Math.max(1 - Math.max((p - 0.52) / 0.06, 0), 0)
      midRef.current.style.opacity = String(fadeIn * fadeOut)
    }
    if (surfaceRef.current) {
      // Fade in at Act 3, stay visible through blackout, fade out slowly into darkness
      const fadeIn  = Math.min(Math.max((p - 0.70) / 0.08, 0), 1)
      const fadeOut = Math.max(1 - Math.max((p - 0.80) / 0.10, 0), 0)
      surfaceRef.current.style.opacity = String(fadeIn * fadeOut)
    }
    if (blackoutRef.current) {
      // Start early, finish well before sticky releases (p≈1.0)
      const cover = p > 0.74 ? Math.min((p - 0.74) / 0.12, 1) : 0
      blackoutRef.current.style.opacity = String(cover)
    }
  }, [])

  if (!loading && accessToken) return <Navigate to="/app" replace />

  return (
    <div style={{ background: '#020408', color: '#e8e8f0' }}>
      <EarthScene onProgress={handleProgress}>
        <HeroOverlay heroRef={heroRef} />
        <ApproachOverlay midRef={midRef} />
        <SurfaceOverlay surfaceRef={surfaceRef} />
        {/* Blackout: covers canvas so stars/Earth are gone before sticky releases */}
        <div
          ref={blackoutRef}
          style={{
            position: 'absolute', inset: 0,
            background: '#020408',
            opacity: 0,
            pointerEvents: 'none',
            zIndex: 5,
          }}
        />
      </EarthScene>

      {/* Negative margin pulls IntroSection up by one viewport height,
          eliminating the dead-scroll gap after the sticky releases */}
      <div style={{ marginTop: '-100dvh', position: 'relative', zIndex: 10 }}>
        <IntroSection />
      </div>
    </div>
  )
}
