import { useState, useRef, useCallback } from 'react'
import gsap from 'gsap'
import { streamGenerate, NODE_PROGRESS, type GenerateRequest } from '../api'
import type { Settings } from '../SettingsDrawer'

export type Phase = 'idle' | 'generating' | 'done' | 'error'

interface Options {
  topic:       string
  duration:    number
  voice:       string
  settings:    Settings
  accessToken: string | null
}

export function useStoryGeneration({ topic, duration, voice, settings, accessToken }: Options) {
  const [phase,    setPhase]    = useState<Phase>('idle')
  const [status,   setStatus]   = useState('')
  const [progress, setProgress] = useState(0)
  const [story,    setStory]    = useState('')
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [ttsError, setTtsError] = useState<string | null>(null)
  const [errorMsg, setErrorMsg] = useState('')

  const abortRef         = useRef<AbortController | null>(null)
  const progressTweenRef = useRef<gsap.core.Tween | null>(null)
  const progressProxy    = useRef({ value: 0 })

  const start = useCallback(async () => {
    if (!topic.trim()) return

    const ctrl = new AbortController()
    abortRef.current = ctrl

    setPhase('generating')
    setProgress(0)
    setStatus('Starting…')
    setStory('')
    setAudioUrl(null)
    setTtsError(null)
    setErrorMsg('')

    const req: GenerateRequest = {
      topic:        topic.trim(),
      duration_min: duration,
      style:        settings.style,
      audience:     settings.audience,
      domain:       'general science',
      voice,
    }

    const creep = (from: number, to: number, dur: number) => {
      progressTweenRef.current?.kill()
      progressProxy.current.value = from
      progressTweenRef.current = gsap.to(progressProxy.current, {
        value: to, duration: dur, ease: 'none',
        onUpdate: () => {
          const v = Math.round(progressProxy.current.value)
          setProgress(p => v > p ? v : p)
        },
      })
    }

    try {
      for await (const ev of streamGenerate(req, ctrl.signal, accessToken ?? undefined)) {
        if (ev.event === 'node_done') {
          const pct = NODE_PROGRESS[ev.node] ?? 0
          progressTweenRef.current?.kill()
          setProgress(p => Math.max(p, pct))

          if (ev.node === 'assemble_chapters') {
            setStatus('Polishing story…')
            creep(pct, 91, 90)
          } else if (ev.node === 'polish_story') {
            setStatus('Synthesizing audio…')
            creep(pct, 99, 60)
          } else {
            setStatus(ev.message || ev.node)
          }
        } else if (ev.event === 'done') {
          progressTweenRef.current?.kill()
          setProgress(100)
          setStory(ev.final_story)
          setAudioUrl(ev.audio_url)
          setTtsError(ev.tts_error ?? null)
          setPhase('done')
        } else if (ev.event === 'error') {
          throw new Error(ev.message)
        }
      }
    } catch (e: unknown) {
      if ((e as { name?: string }).name === 'AbortError') return
      setErrorMsg(e instanceof Error ? e.message : String(e))
      setPhase('error')
    }
  }, [topic, duration, voice, settings, accessToken])

  const reset = useCallback(() => {
    abortRef.current?.abort()
    progressTweenRef.current?.kill()
    setPhase('idle')
    setStory('')
    setAudioUrl(null)
    setTtsError(null)
    setErrorMsg('')
    setProgress(0)
    setStatus('')
  }, [])

  return { phase, status, progress, story, audioUrl, ttsError, errorMsg, abortRef, start, reset }
}
