export type ThemeName = 'cosmos' | 'life' | 'civilization' | 'default'

export interface Theme {
  name: ThemeName
  bg: string          // CSS background gradient
  particleColor: string
  accentColor: string
  ambient: string
}

const COSMOS_WORDS  = ['universe','cosmos','space','galaxy','star','big bang','astronomy',
                        'cosmic','planet','black hole','nebula','supernova','quasar','dark matter',
                        'quantum','physics','light','photon']
const LIFE_WORDS    = ['biology','evolution','life','species','animal','plant','tree',
                        'forest','creature','dna','cell','nature','ecosystem','dinosaur',
                        'ocean','coral','fungi','mushroom','bird','migration']
const HISTORY_WORDS = ['history','civilization','ancient','rome','egypt','dynasty','war',
                        'culture','empire','greek','human','society','archaeology','medieval',
                        'mesopotamia','silk road','renaissance','mythology']

export function inferTheme(topic: string): Theme {
  const t = topic.toLowerCase()
  if (COSMOS_WORDS.some(w => t.includes(w)))    return THEMES.cosmos
  if (HISTORY_WORDS.some(w => t.includes(w)))   return THEMES.civilization
  if (LIFE_WORDS.some(w => t.includes(w)))       return THEMES.life
  return THEMES.default
}

export const THEMES: Record<ThemeName, Theme> = {
  cosmos: {
    name: 'cosmos',
    bg: 'radial-gradient(ellipse at 50% 80%, #0d0d2b 0%, #050510 60%, #000005 100%)',
    particleColor: '#c8d8ff',
    accentColor: '#8ab4f8',
    ambient: 'cosmos',
  },
  life: {
    name: 'life',
    bg: 'radial-gradient(ellipse at 50% 100%, #071a0e 0%, #030f07 60%, #010801 100%)',
    particleColor: '#a8d8a8',
    accentColor: '#6fcf97',
    ambient: 'woods',
  },
  civilization: {
    name: 'civilization',
    bg: 'radial-gradient(ellipse at 50% 100%, #1a0d04 0%, #0f0703 60%, #080401 100%)',
    particleColor: '#f4c87a',
    accentColor: '#e0a050',
    ambient: 'fire',
  },
  default: {
    name: 'default',
    bg: 'radial-gradient(ellipse at 50% 80%, #0a0f1a 0%, #050810 60%, #020408 100%)',
    particleColor: '#a0b8d0',
    accentColor: '#7fa8c8',
    ambient: 'rain',
  },
}
