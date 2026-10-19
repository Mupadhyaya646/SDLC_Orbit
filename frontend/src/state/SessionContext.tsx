import { createContext, useContext, useState, type ReactNode } from 'react'

export type Tab = 'session' | 'pipeline' | 'agents' | 'log' | 'journal'

interface SessionContextValue {
  tab: Tab
  setTab: (t: Tab) => void
  sid: string | null
  setSid: (sid: string | null) => void
  draftRequest: string
  setDraftRequest: (text: string) => void
  selected: number | null
  setSelected: (i: number | null) => void
  note: string
  setNote: (note: string) => void
  reset: () => void
}

const SessionContext = createContext<SessionContextValue | null>(null)

export function SessionProvider({ children }: { children: ReactNode }) {
  const [tab, setTabState] = useState<Tab>('session')
  const [sid, setSid] = useState<string | null>(null)
  const [draftRequest, setDraftRequest] = useState('')
  const [selected, setSelected] = useState<number | null>(null)
  const [note, setNote] = useState('')

  const setTab = (t: Tab) => {
    setTabState(t)
    if (t !== 'pipeline') setSelected(null)
  }

  const reset = () => {
    setSid(null)
    setDraftRequest('')
    setSelected(null)
    setNote('')
    setTabState('session')
  }

  return (
    <SessionContext.Provider
      value={{ tab, setTab, sid, setSid, draftRequest, setDraftRequest, selected, setSelected, note, setNote, reset }}
    >
      {children}
    </SessionContext.Provider>
  )
}

export function useSessionUi(): SessionContextValue {
  const ctx = useContext(SessionContext)
  if (!ctx) throw new Error('useSessionUi must be used within a SessionProvider')
  return ctx
}
