declare module 'vanta/dist/vanta.fog.min' {
  import * as THREE from 'three'
  interface VantaFogOptions {
    el: HTMLElement | null
    THREE: typeof THREE
    highlightColor?: number
    midtoneColor?: number
    lowlightColor?: number
    baseColor?: number
    blurFactor?: number
    speed?: number
    zoom?: number
  }
  interface VantaEffect {
    destroy(): void
  }
  export default function FOG(options: VantaFogOptions): VantaEffect
}
