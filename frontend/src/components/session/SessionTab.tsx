import { EXAMPLES, DEFAULT_ROSTER, AGENT_INITIALS } from '../../constants'
import { useSessionUi } from '../../state/SessionContext'
import { useStartSession } from '../../hooks/useStartSession'
import { LoadingButton } from '../shared/LoadingButton'
import { StatusMark } from '../shared/StatusMark'
import { headerStatus } from '../../lib/stageDerivation'
import { useSession } from '../../hooks/useSession'
import { baseAgentId } from '../../lib/stageDerivation'

export function SessionTab() {
  const { sid } = useSessionUi()
  return (
    <div className="lds-in" style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1.55fr) minmax(340px,1fr)', gap: 24, padding: '28px 32px', alignItems: 'start' }}>
      <section className="card" style={{ padding: 28 }}>
        <div style={{ width: 80, height: 8, background: 'var(--red)', marginBottom: 24 }} />
        <div className="mono" style={{ fontSize: 11, letterSpacing: '.14em', color: 'var(--red-text)', textTransform: 'uppercase' }}>
          New request
        </div>
        <h1 style={{ margin: '8px 0 6px', fontSize: 30, lineHeight: 1.15, fontWeight: 600, letterSpacing: '-.015em' }}>
          What should the pipeline implement?
        </h1>
        <p style={{ margin: '0 0 20px', color: 'var(--ink2)', maxWidth: '62ch' }}>
          Describe the Salesforce change in plain language. The pipeline runs seven stages and pauses whenever a
          specialist needs your approval.
        </p>
        {sid ? <LockedBody /> : <RequestForm />}
      </section>
      <SpecialistRoster />
    </div>
  )
}

function RequestForm() {
  const { draftRequest, setDraftRequest } = useSessionUi()
  const startSession = useStartSession()
  const { setSid, setTab } = useSessionUi()

  const onStart = () => {
    const text = draftRequest.trim()
    if (!text) return
    startSession.mutate(
      { text },
      {
        onSuccess: (r) => {
          setSid(r.id)
          setTab('pipeline')
        },
        onError: (e) => alert('Could not start session: ' + e.message),
      },
    )
  }

  return (
    <>
      <textarea
        rows={9}
        placeholder="Example: Add an Enrollment Source picklist to Enrollment__c, show it on the record page, and add test coverage for the routing flow."
        value={draftRequest}
        onChange={(e) => setDraftRequest(e.target.value)}
        onKeyDown={(e) => {
          if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') onStart()
        }}
        style={{
          width: '100%',
          minHeight: 220,
          resize: 'vertical',
          border: '1px solid var(--line2)',
          background: 'var(--bg)',
          color: 'var(--ink)',
          padding: 16,
          font: "400 15px/1.6 'IBM Plex Sans',sans-serif",
        }}
      />
      <div className="mono" style={{ display: 'flex', justifyContent: 'space-between', gap: 8, marginTop: 8 }}>
        <span style={{ fontSize: 11, color: 'var(--muted)' }}>{draftRequest.length} characters</span>
        <span style={{ fontSize: 11, color: 'var(--muted)' }}>Ctrl / Cmd + Enter to start</span>
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8, marginTop: 16 }}>
        <span
          className="mono"
          style={{ fontSize: 11, letterSpacing: '.1em', color: 'var(--muted)', textTransform: 'uppercase', marginRight: 4 }}
        >
          Try
        </span>
        {EXAMPLES.map(([label, text], i) => (
          <button
            key={i}
            onClick={() => setDraftRequest(text)}
            style={{
              border: '1px solid var(--line2)',
              background: 'transparent',
              color: 'var(--ink2)',
              padding: '6px 12px',
              font: "400 13px 'IBM Plex Sans',sans-serif",
              cursor: 'pointer',
            }}
          >
            {label}
          </button>
        ))}
      </div>
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'center',
          justifyContent: 'flex-end',
          gap: 16,
          marginTop: 24,
          paddingTop: 20,
          borderTop: '1px solid var(--line)',
        }}
      >
        <LoadingButton isLoading={startSession.isPending} disabled={draftRequest.length === 0} onClick={onStart}>
          Start session<span className="mono" style={{ opacity: 0.8 }}>&rarr;</span>
        </LoadingButton>
      </div>
    </>
  )
}

function LockedBody() {
  const { sid, draftRequest, setTab, reset } = useSessionUi()
  const { data: session } = useSession(sid)
  const hs = headerStatus(session ?? null)

  const onEnd = () => reset()

  return (
    <>
      <textarea
        rows={9}
        readOnly
        value={draftRequest}
        style={{
          width: '100%',
          minHeight: 220,
          resize: 'vertical',
          border: '1px solid var(--line2)',
          background: 'var(--bg)',
          color: 'var(--ink)',
          padding: 16,
          font: "400 15px/1.6 'IBM Plex Sans',sans-serif",
        }}
      />
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 16,
          marginTop: 20,
          padding: 16,
          background: 'var(--red-soft)',
          border: '1px solid var(--line2)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <StatusMark status={hs.s} />
          <div>
            <div style={{ fontWeight: 600 }}>
              Session <span className="mono">{sid}</span> &middot; {hs.l}
            </div>
            <div style={{ fontSize: 13, color: 'var(--ink2)' }}>The request is locked while the session runs.</div>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <LoadingButton onClick={() => setTab('pipeline')}>Open pipeline</LoadingButton>
          <LoadingButton variant="secondary" onClick={onEnd}>
            End session
          </LoadingButton>
        </div>
      </div>
    </>
  )
}

function SpecialistRoster() {
  const roster = DEFAULT_ROSTER
  return (
    <aside className="card">
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'baseline',
          padding: '18px 20px',
          borderBottom: '1px solid var(--line)',
        }}
      >
        <div style={{ font: "600 15px 'IBM Plex Sans',sans-serif" }}>Specialist agents</div>
        <div className="mono" style={{ fontSize: 12, color: 'var(--muted)' }}>
          {roster.length} available
        </div>
      </div>
      <div>
        {roster.map((a) => (
          <div
            key={a.id}
            style={{ display: 'grid', gridTemplateColumns: '32px minmax(0,1fr)', gap: 12, padding: '13px 20px', borderBottom: '1px solid var(--line)' }}
          >
            <div
              className="mono"
              style={{
                width: 32,
                height: 32,
                border: '1px solid var(--line2)',
                background: 'var(--surface2)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: 11,
                fontWeight: 600,
              }}
            >
              {AGENT_INITIALS[baseAgentId(a.id)] || '??'}
            </div>
            <div style={{ minWidth: 0 }}>
              <div className="mono" style={{ fontWeight: 500, fontSize: 13 }}>
                {a.id}
              </div>
              <div style={{ fontSize: 13, color: 'var(--ink2)' }}>{a.short}</div>
            </div>
          </div>
        ))}
      </div>
    </aside>
  )
}
