import { useEffect } from 'react'
import { lastGateQuestionForStage, stageIndexFromState, whoForStage } from '../lib/stageDerivation'
import { parseOptions } from '../lib/parseOptions'
import type { Session, Turn } from '../types'

interface Params {
  tab: string
  session: Session | null
  turns: Turn[]
  selected: number | null
  isPending: boolean
  onAnswer: (key: string, agent: string | null) => void
}

export function useKeyboardGateShortcuts({ tab, session, turns, selected, isPending, onAnswer }: Params) {
  useEffect(() => {
    function handler(e: KeyboardEvent) {
      if (tab !== 'pipeline' || !session || session.status !== 'awaiting_input') return
      if (isPending) return
      if (e.metaKey || e.ctrlKey || e.altKey) return
      const tg = (e.target as HTMLElement | null)?.tagName
      if (tg === 'TEXTAREA' || tg === 'INPUT') return
      const state = session.pipeline_state
      if (!state) return
      const current = stageIndexFromState(state)
      if (selected !== null && selected !== current) return
      const gate = lastGateQuestionForStage(turns, current)
      if (!gate) return
      const options = parseOptions(gate.question)
      const k = e.key.toUpperCase()
      if (options.some(([optKey]) => optKey.toUpperCase() === k)) {
        e.preventDefault()
        onAnswer(k, whoForStage(session, current))
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [tab, session, turns, selected, isPending, onAnswer])
}
