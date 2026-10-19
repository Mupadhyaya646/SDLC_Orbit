import { useState } from 'react'
import { useSessionUi } from '../../state/SessionContext'
import { useAgents } from '../../hooks/useAgents'
import { AGENT_INITIALS, AL, STAGE_NAMES } from '../../constants'
import { baseAgentId } from '../../lib/stageDerivation'
import { StatusMark } from '../shared/StatusMark'
import { formatTime } from '../../lib/formatTime'
import type { AgentRuntimeStatus } from '../../types'

const CHIP_DEFS: Array<[string, string, AgentRuntimeStatus | null]> = [
  ['all', 'All', null],
  ['running', 'Running', 'running'],
  ['awaiting', 'Awaiting input', 'awaiting'],
  ['done', 'Done', 'done'],
  ['idle', 'Idle', 'idle'],
  ['failed', 'Failed', 'failed'],
]

export function AgentsTab() {
  const { sid, tab } = useSessionUi()
  const { data } = useAgents(sid, tab === 'agents')
  const [filter, setFilter] = useState('all')
  const agents = data?.agents ?? []

  const chips = CHIP_DEFS.map(([key, label, st]) => {
    const count = agents.filter((a) => !st || a.status === st).length
    const on = filter === key
    return (
      <button
        key={key}
        onClick={() => setFilter(key)}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 8,
          padding: '7px 14px',
          font: "500 13px 'IBM Plex Sans',sans-serif",
          cursor: 'pointer',
          border: '1px solid ' + (on ? 'var(--ink)' : 'var(--line2)'),
          background: on ? 'var(--ink)' : 'var(--surface)',
          color: on ? 'var(--bg)' : 'var(--ink2)',
        }}
      >
        {st && <StatusMark status={st} />}
        <span>{label}</span>
        <span className="mono" style={{ fontSize: 12, color: 'var(--muted)' }}>
          {count}
        </span>
      </button>
    )
  })

  const cards = agents
    .filter((a) => filter === 'all' || a.status === filter)
    .map((a) => {
      const color = a.status === 'awaiting' || a.status === 'failed' ? 'var(--red-text)' : a.status === 'running' ? 'var(--blue)' : a.status === 'done' ? 'var(--ink)' : 'var(--muted)'
      const borderColor = a.status === 'awaiting' ? 'var(--red)' : a.status === 'failed' ? 'var(--red-text)' : 'var(--line)'
      return (
        <article
          key={a.id}
          className="card"
          style={{
            display: 'flex',
            flexDirection: 'column',
            padding: 20,
            borderColor,
            boxShadow: a.status === 'awaiting' ? '0 0 0 1px var(--red)' : undefined,
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, minWidth: 0 }}>
              <div
                style={{
                  width: 40,
                  height: 40,
                  flex: 'none',
                  border: '1px solid var(--line2)',
                  background: 'var(--surface2)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  font: "600 13px 'IBM Plex Mono',monospace",
                }}
              >
                {AGENT_INITIALS[baseAgentId(a.id)] || '??'}
              </div>
              <div className="mono" style={{ fontWeight: 600, fontSize: 14, overflowWrap: 'anywhere' }}>
                {a.id}
              </div>
            </div>
            <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontSize: 12, fontWeight: 500, whiteSpace: 'nowrap', color }}>
              <StatusMark status={a.status} />
              {AL[a.status]}
            </div>
          </div>
          <p style={{ margin: '14px 0 0', color: 'var(--ink2)' }}>{a.role}</p>
          <div style={{ marginTop: 'auto', paddingTop: 16 }}>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, paddingTop: 14, borderTop: '1px solid var(--line)' }}>
              {(a.stages || []).map((si) => (
                <span key={si} className="mono" style={{ fontSize: 12, padding: '2px 8px', border: '1px solid var(--line2)', color: 'var(--ink2)' }}>
                  <span style={{ color: 'var(--muted)' }}>{String(si + 1).padStart(2, '0')}</span> {STAGE_NAMES[si]}
                </span>
              ))}
            </div>
            <div className="mono" style={{ marginTop: 10, fontSize: 11, color: 'var(--muted)' }}>
              Last activity {a.last_activity ? formatTime(a.last_activity) : '—'}
            </div>
          </div>
        </article>
      )
    })

  return (
    <div className="lds-in" style={{ padding: '28px 32px' }}>
      <div style={{ marginBottom: 20 }}>
        <h2 style={{ margin: 0, fontSize: 28, fontWeight: 600, letterSpacing: '-.02em' }}>Agents</h2>
        <div style={{ color: 'var(--ink2)', marginTop: 2 }}>Every specialist in the pipeline, with live status and the stages it works.</div>
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 20 }}>{chips}</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(min(100%,320px),1fr))', gap: 16 }}>
        {cards.length > 0 ? cards : <div style={{ padding: 28, color: 'var(--muted)' }}>No agents yet.</div>}
      </div>
    </div>
  )
}
