import { useState } from 'react'
import { useSessionUi } from '../../state/SessionContext'
import { useLog } from '../../hooks/useLog'
import { formatTime } from '../../lib/formatTime'
import type { LogEntry } from '../../types'

const LOG_CHIP_DEFS: Array<[string, string]> = [
  ['all', 'All'],
  ['turn', 'Turns'],
  ['decision', 'Decisions'],
  ['error', 'Errors'],
]

function matchesFilter(e: LogEntry, f: string): boolean {
  if (f === 'all') return true
  if (f === 'error') return !e.ok
  return e.kind === f
}

export function LogTab() {
  const { sid, tab } = useSessionUi()
  const { data } = useLog(sid, tab === 'log')
  const [filter, setFilter] = useState('all')
  const [openRows, setOpenRows] = useState<Record<number, boolean>>({})
  const entries = data?.entries ?? []

  const chips = LOG_CHIP_DEFS.map(([key, label]) => {
    const count = entries.filter((e) => matchesFilter(e, key)).length
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
        <span>{label}</span>
        <span className="mono" style={{ fontSize: 12, color: 'var(--muted)' }}>
          {count}
        </span>
      </button>
    )
  })

  const rowsAll = entries.filter((e) => matchesFilter(e, filter))
  const cols = '44px 150px 170px 88px minmax(0,1fr)'

  return (
    <div className="lds-in" style={{ padding: '28px 32px' }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'flex-end', gap: '12px 24px', marginBottom: 16 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 28, fontWeight: 600, letterSpacing: '-.02em' }}>Log</h2>
          <div style={{ color: 'var(--ink2)', marginTop: 2 }}>Every raw turn and decision in this session, in order. Select a row for the payload.</div>
        </div>
        <div className="mono" style={{ fontSize: 12, color: 'var(--muted)' }}>
          {rowsAll.length} of {entries.length} entries
        </div>
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 16 }}>{chips}</div>
      <div className="card" style={{ overflowX: 'auto' }}>
        <div style={{ minWidth: 560 }}>
          <div
            className="mono"
            style={{
              display: 'grid',
              gridTemplateColumns: cols,
              gap: 12,
              padding: '10px 16px',
              borderBottom: '1px solid var(--line)',
              background: 'var(--surface2)',
              fontSize: 11,
              fontWeight: 500,
              letterSpacing: '.1em',
              textTransform: 'uppercase',
              color: 'var(--muted)',
            }}
          >
            <span>#</span>
            <span>Time</span>
            <span>Agent</span>
            <span>Type</span>
            <span>Summary</span>
          </div>
          {rowsAll.length === 0 ? (
            <div style={{ padding: '48px 16px', textAlign: 'center', color: 'var(--muted)' }}>
              {entries.length ? 'No entries match this filter.' : 'No entries yet. Start a session to record turns and decisions.'}
            </div>
          ) : (
            rowsAll.map((e) => {
              const kindColor = !e.ok ? 'var(--red-text)' : e.kind === 'decision' ? 'var(--ink)' : 'var(--muted)'
              const open = !!openRows[e.n]
              return (
                <div key={e.n} style={{ borderBottom: '1px solid var(--line)', background: e.ok ? 'transparent' : 'var(--red-soft)' }}>
                  <div
                    className="mono"
                    onClick={() => setOpenRows((prev) => ({ ...prev, [e.n]: !prev[e.n] }))}
                    style={{ display: 'grid', gridTemplateColumns: cols, gap: 12, padding: '9px 16px', alignItems: 'baseline', cursor: 'pointer' }}
                  >
                    <span style={{ color: 'var(--muted)' }}>{String(e.n).padStart(3, '0')}</span>
                    <span style={{ color: 'var(--ink2)', fontSize: 12 }}>{formatTime(e.time)}</span>
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 12 }}>{e.agent}</span>
                    <span style={{ fontSize: 11, letterSpacing: '.06em', textTransform: 'uppercase', fontWeight: 600, color: kindColor }}>
                      {e.kind}
                      {!e.ok ? ' · failed' : ''}
                    </span>
                    <span
                      style={{
                        fontFamily: "'IBM Plex Sans',sans-serif",
                        fontSize: 13,
                        color: 'var(--ink)',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {e.summary}
                    </span>
                  </div>
                  {open && (
                    <pre
                      style={{
                        margin: 0,
                        padding: '12px 16px 16px',
                        background: 'var(--bg)',
                        borderTop: '1px solid var(--line)',
                        font: "400 12px/1.6 'IBM Plex Mono',monospace",
                        color: 'var(--ink2)',
                        whiteSpace: 'pre-wrap',
                        overflowWrap: 'anywhere',
                      }}
                    >
                      {JSON.stringify(e.raw, null, 2)}
                    </pre>
                  )}
                </div>
              )
            })
          )}
        </div>
      </div>
    </div>
  )
}
