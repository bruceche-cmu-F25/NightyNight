import { useState, useEffect } from 'react'
import { useAuth } from '../context/AuthContext'
import type { Settings } from '../SettingsDrawer'

const DEFAULT_SETTINGS: Settings = {
  ambient:  'auto',
  audience: 'curious adults',
  style:    'gentle bedtime',
}

export function useStorySettings() {
  const { user } = useAuth()
  const [voice,    setVoice]    = useState('Blake')
  const [settings, setSettings] = useState<Settings>(DEFAULT_SETTINGS)

  useEffect(() => {
    if (!user?.preferences) return
    if (user.preferences.voice)    setVoice(user.preferences.voice)
    if (user.preferences.audience) setSettings(s => ({ ...s, audience: user.preferences.audience! }))
    if (user.preferences.style)    setSettings(s => ({ ...s, style: user.preferences.style! }))
  }, [user?.preferences?.voice, user?.preferences?.audience, user?.preferences?.style])

  return { voice, setVoice, settings, setSettings }
}
