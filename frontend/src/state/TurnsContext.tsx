import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import type { ConnectionStatus, SSEEvent, Turn } from '../types'

interface TurnsContextValue {
  turns: Turn[]
  connectionStatus: ConnectionStatus
  clear: () => void
}

const TurnsContext = createContext<TurnsContextValue | null>(null)

export function TurnsProvider({ sid, children }: { sid: string | null; children: ReactNode }) {
  const [turns, setTurns] = useState<Turn[]>([])
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>('connected')
  const seenSeq = useRef<Set<number>>(new Set())

  useEffect(() => {
    seenSeq.current = new Set()
    setTurns([])
    if (!sid) return

    const es = new EventSource(`/api/sessions/${sid}/events`)

    es.onmessage = (m) => {
      try {
        const ev = JSON.parse(m.data) as SSEEvent
        if (seenSeq.current.has(ev.seq)) return
        seenSeq.current.add(ev.seq)
        if (ev.kind === 'user' || ev.kind === 'agent_text') {
          setTurns((prev) => [
            ...prev,
            { agent: ev.data.agent, text: ev.data.text, created_at: ev.data.created_at, role: ev.kind, stage: ev.data.stage ?? null },
          ])
        }
      } catch {
        // ignore malformed frames
      }
    }
    es.onerror = () => setConnectionStatus('reconnecting')
    es.onopen = () => setConnectionStatus('connected')

    return () => es.close()
  }, [sid])

  const clear = () => {
    seenSeq.current = new Set()
    setTurns([])
  }

  return <TurnsContext.Provider value={{ turns, connectionStatus, clear }}>{children}</TurnsContext.Provider>
}

export function useTurns(): TurnsContextValue {
  const ctx = useContext(TurnsContext)
  if (!ctx) throw new Error('useTurns must be used within a TurnsProvider')
  return ctx
}
