import { useSessionUi } from '../../state/SessionContext'
import { useJournal } from '../../hooks/useJournal'
import { formatTime } from '../../lib/formatTime'

export function JournalTab() {
  const { sid, tab } = useSessionUi()
  const { data } = useJournal(sid, tab === 'journal')
  const entries = data?.entries ?? []
  const answered = entries.filter((j) => !j.pending)
  const pending = entries.filter((j) => j.pending)

  const stats: Array<{ value: number; label: string; color: string }> = [
    { value: answered.length, label: 'Decisions recorded', color: 'var(--ink)' },
    { value: pending.length, label: 'Awaiting you', color: pending.length ? 'var(--red-text)' : 'var(--ink)' },
  ]

  return (
    <div className="lds-in" style={{ padding: '28px 32px' }}>
      <div style={{ marginBottom: 20 }}>
        <h2 style={{ margin: 0, fontSize: 28, fontWeight: 600, letterSpacing: '-.02em' }}>Journal</h2>
        <div style={{ color: 'var(--ink2)', marginTop: 2 }}>Audit record of every decision point: who answered, what they chose, and when.</div>
      </div>
      <div className="card" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(200px,1fr))', marginBottom: 20 }}>
        {stats.map((x) => (
          <div key={x.label} style={{ padding: '18px 20px', borderRight: '1px solid var(--line)' }}>
            <div style={{ font: "900 34px 'Ringside XW',sans-serif", letterSpacing: '-.04em', lineHeight: 1, color: x.color }}>{x.value}</div>
            <div className="mono" style={{ fontSize: 11, letterSpacing: '.1em', textTransform: 'uppercase', color: 'var(--muted)', marginTop: 8 }}>
              {x.label}
            </div>
          </div>
        ))}
      </div>
      {entries.length === 0 ? (
        <div style={{ padding: '48px 16px', textAlign: 'center', color: 'var(--muted)', border: '1px dashed var(--line2)' }}>
          No decisions recorded yet. Entries appear as you answer decision points.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {entries.map((j) => {
            const style = j.pending
              ? { padding: '18px 20px', background: 'var(--red-soft)', border: '1px solid var(--red)' }
              : { padding: '18px 20px', background: 'var(--surface)', border: '1px solid var(--line)' }
            const keyStyle = j.pending
              ? { font: "600 12px 'IBM Plex Mono',monospace", padding: '2px 8px', border: '1px dashed var(--red-text)', color: 'var(--red-text)' }
              : { font: "600 12px 'IBM Plex Mono',monospace", padding: '2px 8px', border: '1px solid var(--ink)', color: 'var(--ink)' }
            return (
              <article key={j.id} style={style}>
                <div className="mono" style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', gap: '6px 16px', fontSize: 12, color: 'var(--muted)' }}>
                  <span>
                    <span style={{ color: 'var(--ink)', fontWeight: 600 }}>{j.id}</span> &middot; {j.agent}
                  </span>
                  <span>{j.pending ? 'Pending' : formatTime(j.answered_at)}</span>
                </div>
                <div style={{ margin: '10px 0 14px', fontSize: 17, fontWeight: 600, lineHeight: 1.35, whiteSpace: 'pre-wrap' }}>{j.question}</div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(220px,1fr))', gap: '12px 24px', alignItems: 'start' }}>
                  <div>
                    <div className="mono" style={{ fontSize: 11, letterSpacing: '.1em', textTransform: 'uppercase', color: 'var(--muted)', marginBottom: 6 }}>
                      Response
                    </div>
                    <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontWeight: 500 }}>
                      {j.pending ? (
                        <>
                          <span style={keyStyle}>&ndash;</span>
                          Awaiting your response
                        </>
                      ) : (
                        <>
                          <span style={keyStyle}>{j.answer}</span>
                          {j.answer}
                        </>
                      )}
                    </div>
                  </div>
                  <div>
                    <div className="mono" style={{ fontSize: 11, letterSpacing: '.1em', textTransform: 'uppercase', color: 'var(--muted)', marginBottom: 6 }}>
                      Answered by
                    </div>
                    <div style={{ fontWeight: 500 }}>{j.pending ? 'Unassigned' : j.answered_by || 'you'}</div>
                  </div>
                </div>
              </article>
            )
          })}
        </div>
      )}
    </div>
  )
}
