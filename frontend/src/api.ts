export interface GenerateRequest {
  topic: string
  duration_min: number
  style: string
  audience: string
  domain: string
  voice: string
}

export interface NodeDoneEvent {
  event: 'node_done'
  node: string
  chapter: number | null
  progress: number
  message: string
}

export interface DoneEvent {
  event: 'done'
  final_story: string
  audio_url: string | null
  tts_error: string | null
}

export interface ErrorEvent {
  event: 'error'
  message: string
}

export type SSEEvent = NodeDoneEvent | DoneEvent | ErrorEvent

export async function* streamGenerate(req: GenerateRequest, signal?: AbortSignal, token?: string): AsyncGenerator<SSEEvent> {
  const resp = await fetch('/generate', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(req),
    credentials: 'include',
    signal,
  })

  if (!resp.ok) throw new Error(`Server error ${resp.status}`)

  const reader = resp.body!.getReader()
  const decoder = new TextDecoder()
  let buf = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })

    const lines = buf.split('\n')
    buf = lines.pop() ?? ''

    for (const line of lines) {
      if (!line.startsWith('data:')) continue
      try {
        const data = JSON.parse(line.slice(5).trim()) as SSEEvent
        yield data
      } catch {
        // malformed line — skip
      }
    }
  }
}
