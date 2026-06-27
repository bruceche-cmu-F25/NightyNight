/**
 * Scroll progress (0–1) boundaries for the landing page Earth scene.
 * Both EarthScene.tsx (camera) and LandingPage.tsx (overlays) import from here.
 * Change a number here and both files stay in sync automatically.
 */
export const SCROLL_ACTS = {
  hero:     { start: 0.00, end: 0.20 },
  pullback: { start: 0.20, end: 0.50 },
  hold:     { start: 0.50, end: 0.66 },
  approach: { start: 0.66, end: 0.82 },
  enter:    { start: 0.82, end: 1.00 },

  snapPoints: [0, 0.30, 0.60, 0.80, 1.0] as number[],

  overlays: {
    hero:     { fadeOutStart: 0.12, fadeOutEnd:  0.18  },
    pullback: { fadeInStart:  0.22, fadeInEnd:   0.30, fadeOutStart: 0.32, fadeOutEnd: 0.38 },
    hold:     { fadeInStart:  0.50, fadeInEnd:   0.58, fadeOutStart: 0.62, fadeOutEnd: 0.68 },
    surface:  { fadeInStart:  0.72, fadeInEnd:   0.80, fadeOutStart: 0.80, fadeOutEnd: 0.84 },
    blackout: { start: 0.80, end: 0.855 },
  },
} as const
