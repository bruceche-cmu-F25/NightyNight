export interface Theme {
  bg: string
  accentColor: string
}

export const THEMES = {
  default: {
    bg: 'radial-gradient(ellipse at 50% 80%, #0a0f1a 0%, #050810 60%, #020408 100%)',
    accentColor: '#7fa8c8',
  },
} satisfies Record<string, Theme>
