import { useState } from 'react'
import { useSessionUi } from '../../state/SessionContext'
import { useTurns } from '../../state/TurnsContext'
import { useSession } from '../../hooks/useSession'
import { useReplyToGate } from '../../hooks/useReplyToGate'
import { useKeyboardGateShortcuts } from '../../hooks/useKeyboardGateShortcuts'
import { STAGE_NAMES, STAGE_DESC, STAGE_AGENT_IDS, AGENT_INITIALS, SL, SC } from '../../constants'
import {
  stageIndexFromState,
  stageStatuses,
  turnStageIndex,
  lastGateQuestionForStage,
  whoForStage,
  baseAgentId,
} from '../../lib/stageDerivation'
import { parseOptions } from '../../lib/parseOptions'
import { formatTime } from '../../lib/formatTime'
import { StatusMark } from '../shared/StatusMark'
import { LoadingButton } from '../shared/LoadingButton'
import { MarkdownRenderer } from '../shared/MarkdownRenderer'
import type { StageStatus, Turn } from '../../types'

export function PipelineTab() {
  const { sid, setTab } = useSessionUi()
  const { data: session } = useSession(sid)

  if (!sid || !session) {
    return (
      <div className="lds-in" style={{ padding: '28px 32px' }}>
        <div className="card" style={{ border: '1px dashed var(--line2)', padding: '64px 24px', textAlign: 'center' }}>
          <div style={{ font: "600 18px 'IBM Plex Sans',sans-serif" }}>No session running</div>
          <p style={{ margin: '6px auto 20px', color: 'var(--ink2)', maxWidth: '46ch' }}>
            Start a request on the Session tab to see the seven pipeline stages here.
          </p>
          <LoadingButton onClick={() => setTab('session')}>Go to Session</LoadingButton>
        </div>
      </div>
    )
  }

  return <PipelineBody />
}

function PipelineBody() {
  const { sid, selected, setSelected, note, setNote, draftRequest } = useSessionUi()
  const { data: session } = useSession(sid)
  const { turns } = useTurns()
  const replyMutation = useReplyToGate(sid)
  const [pendingKey, setPendingKey] = useState<string | null>(null)

  if (!session) return null

  const state = session.pipeline_state
  const stages = stageStatuses(session)
  const current = state?.step ? stageIndexFromState(state) : 0
  const pendingStage = session.status === 'awaiting_input' ? current : null
  const vi = selected !== null ? selected : current
  const vStatus = stages[vi]
  const doneCount = stages.filter((s) => s === 'done').length

  const who = state ? whoForStage(session, vi) : null

  const onAnswer = (key: string, agent: string | null) => {
    setPendingKey(key)
    const text = note.trim() ? (key.length === 1 ? key + '\n\n' + note.trim() : key.toLowerCase() === 'changes' ? note.trim() : key) : key
    const body = agent ? { text, answered_by: 'you', agent } : { text, answered_by: 'you' }
    replyMutation.mutate(body, {
      onSuccess: () => {
        setNote('')
        setPendingKey(null)
      },
      onError: (e) => {
        alert('Could not send reply: ' + e.message)
        setPendingKey(null)
      },
    })
  }

  const onAnswerFreeText = (text: string, agent: string | null) => {
    setPendingKey('__freetext__')
    const body = agent ? { text, answered_by: 'you', agent } : { text, answered_by: 'you' }
    replyMutation.mutate(body, {
      onSuccess: () => setPendingKey(null),
      onError: (e) => {
        alert('Could not send reply: ' + e.message)
        setPendingKey(null)
      },
    })
  }

  useKeyboardGateShortcuts({
    tab: 'pipeline',
    session,
    turns,
    selected,
    isPending: replyMutation.isPending,
    onAnswer,
  })

  return (
    <div className="lds-in" style={{ padding: '28px 32px' }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginBottom: 20 }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', gap: '6px 24px', alignItems: 'flex-start' }}>
          <div className="mono" style={{ fontSize: 12, color: 'var(--muted)', whiteSpace: 'nowrap' }}>
            <span style={{ color: 'var(--ink)' }}>{sid}</span> &middot; {doneCount} of 7 stages complete
          </div>
          <div
            style={{
              fontSize: 13,
              color: 'var(--ink2)',
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              flex: '1 1 240px',
              minWidth: 0,
              maxWidth: 640,
            }}
          >
            {draftRequest}
          </div>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7,1fr)', gap: 4 }}>
          {stages.map((st, i) => (
            <div
              key={i}
              style={{
                height: 4,
                background: { done: 'var(--ink)', awaiting: 'var(--red)', running: 'var(--blue)', idle: 'var(--line2)', cancelled: 'var(--line2)', failed: 'var(--red-text)' }[st],
                animation: st === 'running' ? 'lds-pulse 1.6s ease-in-out infinite' : undefined,
              }}
            />
          ))}
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '280px minmax(0,1fr)', gap: 24, alignItems: 'start' }}>
        <StageRail stages={stages} vi={vi} onSelect={setSelected} />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20, minWidth: 0 }}>
          <StageHeader vi={vi} vStatus={vStatus} />
          {pendingStage !== null && pendingStage !== vi && (
            <ElsewhereBanner pendingStage={pendingStage} onGo={() => setSelected(pendingStage)} />
          )}
          {pendingStage !== null && pendingStage === vi && (
            <DecisionCard
              vi={vi}
              turns={turns}
              who={who}
              note={note}
              setNote={setNote}
              isPending={replyMutation.isPending}
              pendingKey={pendingKey}
              onAnswer={onAnswer}
              onAnswerFreeText={onAnswerFreeText}
            />
          )}
          <AgentOutputFeed vi={vi} vStatus={vStatus} turns={turns} />
        </div>
      </div>
    </div>
  )
}

function StageRail({ stages, vi, onSelect }: { stages: StageStatus[]; vi: number; onSelect: (i: number) => void }) {
  return (
    <nav style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {STAGE_NAMES.map((name, i) => {
        const st = stages[i]
        const sel = i === vi
        return (
          <button
            key={i}
            onClick={() => onSelect(i)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 12,
              padding: '12px 14px',
              textAlign: 'left',
              fontFamily: 'inherit',
              cursor: 'pointer',
              flex: 'none',
              width: '100%',
              border: '1px solid ' + (sel ? 'var(--ink)' : st === 'awaiting' ? 'var(--red)' : 'var(--line)'),
              background: sel ? 'var(--surface)' : st === 'awaiting' ? 'var(--red-soft)' : 'transparent',
              boxShadow: sel ? '0 0 0 1px var(--ink)' : 'none',
            }}
          >
            <span className="mono" style={{ fontSize: 12, color: 'var(--muted)', flex: 'none' }}>
              {String(i + 1).padStart(2, '0')}
            </span>
            <span style={{ flex: 1, minWidth: 0 }}>
              <span style={{ display: 'block', fontSize: 14, fontWeight: sel ? 600 : 500, color: 'var(--ink)', whiteSpace: 'nowrap' }}>
                {name}
              </span>
              <span style={{ display: 'block', fontSize: 12, color: SC[st], whiteSpace: 'nowrap' }}>{SL[st]}</span>
            </span>
            <StatusMark status={st} />
          </button>
        )
      })}
    </nav>
  )
}

function StageHeader({ vi, vStatus }: { vi: number; vStatus: StageStatus }) {
  return (
    <section className="card" style={{ padding: 28 }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'flex-start', gap: '12px 24px' }}>
        <div style={{ minWidth: 0 }}>
          <div className="mono" style={{ fontSize: 11, letterSpacing: '.14em', color: 'var(--muted)', textTransform: 'uppercase' }}>
            Stage {String(vi + 1).padStart(2, '0')} of 07
          </div>
          <h2 style={{ margin: '4px 0 4px', fontSize: 30, lineHeight: 1.1, fontWeight: 600, letterSpacing: '-.02em' }}>
            {STAGE_NAMES[vi]}
          </h2>
          <div style={{ color: 'var(--ink2)', maxWidth: '60ch' }}>{STAGE_DESC[vi]}</div>
        </div>
        <div
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 8,
            padding: '6px 12px',
            border: '1px solid var(--line2)',
            background: 'var(--bg)',
            fontWeight: 500,
            fontSize: 13,
          }}
        >
          <StatusMark status={vStatus} />
          <span>{SL[vStatus]}</span>
        </div>
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8, marginTop: 18, paddingTop: 16, borderTop: '1px solid var(--line)' }}>
        <span className="mono" style={{ fontSize: 11, letterSpacing: '.1em', color: 'var(--muted)', textTransform: 'uppercase', marginRight: 4 }}>
          Agents
        </span>
        {STAGE_AGENT_IDS[vi].map((id) => (
          <span key={id} style={{ display: 'inline-flex', alignItems: 'center', gap: 8, padding: '3px 10px 3px 3px', border: '1px solid var(--line2)' }}>
            <span
              style={{
                width: 24,
                height: 24,
                background: 'var(--surface2)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                font: "600 10px 'IBM Plex Mono',monospace",
              }}
            >
              {AGENT_INITIALS[id] || '??'}
            </span>
            <span className="mono" style={{ fontSize: 12 }}>
              {id}
            </span>
          </span>
        ))}
      </div>
    </section>
  )
}

function ElsewhereBanner({ pendingStage, onGo }: { pendingStage: number; onGo: () => void }) {
  return (
    <div
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 12,
        padding: '14px 18px',
        border: '1px solid var(--red)',
        background: 'var(--red-soft)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <StatusMark status="awaiting" />
        <span style={{ fontWeight: 500 }}>A decision is waiting at {STAGE_NAMES[pendingStage]}.</span>
      </div>
      <LoadingButton onClick={onGo} style={{ padding: '8px 14px', fontSize: 13 }}>
        Go to decision
      </LoadingButton>
    </div>
  )
}

interface DecisionCardProps {
  vi: number
  turns: Turn[]
  who: string | null
  note: string
  setNote: (n: string) => void
  isPending: boolean
  pendingKey: string | null
  onAnswer: (key: string, agent: string | null) => void
  onAnswerFreeText: (text: string, agent: string | null) => void
}

function DecisionCard({ vi, turns, who, note, setNote, isPending, pendingKey, onAnswer, onAnswerFreeText }: DecisionCardProps) {
  const gate = lastGateQuestionForStage(turns, vi)
  const [freeText, setFreeText] = useState('')
  if (!gate) return null
  const options = parseOptions(gate.question)

  return (
    <section className="card lds-in" style={{ border: '2px solid var(--red)', boxShadow: 'var(--shadow)' }}>
      <div style={{ width: 80, height: 8, background: 'var(--red)' }} />
      <div style={{ padding: 28 }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 12 }}>
          <span
            style={{
              width: 8,
              height: 8,
              borderRadius: '50%',
              background: 'var(--red)',
              animation: 'lds-pulse 1.4s ease-in-out infinite',
            }}
          />
          <span
            className="mono"
            style={{ fontSize: 12, fontWeight: 600, letterSpacing: '.14em', color: 'var(--red-text)', textTransform: 'uppercase' }}
          >
            Decision needed
          </span>
          <span className="mono" style={{ fontSize: 11, color: 'var(--ink2)' }}>
            from {who || ''}
          </span>
        </div>
        <h3 style={{ margin: '10px 0 18px', fontSize: 24, lineHeight: 1.25, fontWeight: 600, letterSpacing: '-.01em', whiteSpace: 'pre-wrap' }}>
          {gate.question}
        </h3>

        {options.length > 0 ? (
          <>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(210px,1fr))', gap: 12 }}>
              {options.map(([key, label], idx) => {
                const kind = key.toUpperCase() === 'X' ? 'x' : idx === 0 ? 'p' : 's'
                const isThisPending = isPending && pendingKey === key
                return (
                  <button
                    key={key}
                    disabled={isPending}
                    onClick={() => onAnswer(key, who)}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 14,
                      padding: '14px 16px',
                      fontFamily: 'inherit',
                      cursor: isPending ? 'not-allowed' : 'pointer',
                      textAlign: 'left',
                      border: '1px solid ' + (kind === 'p' ? 'var(--red)' : 'var(--line2)'),
                      background: kind === 'p' ? 'var(--red)' : kind === 'x' ? 'transparent' : 'var(--surface2)',
                      color: kind === 'p' ? '#fff' : kind === 'x' ? 'var(--red-text)' : 'var(--ink)',
                      opacity: isPending && !isThisPending ? 0.5 : 1,
                    }}
                  >
                    <span
                      style={{
                        flex: 'none',
                        width: 30,
                        height: 30,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        font: "600 14px 'IBM Plex Mono',monospace",
                        background: kind === 'p' ? 'rgba(255,255,255,.22)' : 'transparent',
                        color: kind === 'p' ? '#fff' : 'currentColor',
                        border: kind === 'p' ? 'none' : '1px solid currentColor',
                      }}
                    >
                      {isThisPending ? <span className="btn-spinner" /> : key}
                    </span>
                    <span style={{ display: 'block', textAlign: 'left' }}>
                      <span style={{ display: 'block', fontWeight: 600, fontSize: 15 }}>{label || key}</span>
                    </span>
                  </button>
                )
              })}
            </div>
            <label style={{ display: 'block', marginTop: 20 }}>
              <span
                className="mono"
                style={{ display: 'block', fontSize: 11, letterSpacing: '.1em', textTransform: 'uppercase', color: 'var(--muted)', marginBottom: 6 }}
              >
                Note (optional, sent with your choice)
              </span>
              <textarea
                rows={2}
                placeholder="Add context for the agents or the audit record"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                disabled={isPending}
                style={{
                  width: '100%',
                  resize: 'vertical',
                  border: '1px solid var(--line2)',
                  background: 'var(--bg)',
                  color: 'var(--ink)',
                  padding: '10px 12px',
                  font: "400 14px/1.5 'IBM Plex Sans',sans-serif",
                }}
              />
            </label>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 12, fontSize: 12, color: 'var(--muted)' }}>
              <span
                className="mono"
                style={{ fontSize: 11, fontWeight: 600, padding: '2px 6px', border: '1px solid var(--line2)', borderBottomWidth: 2, color: 'var(--ink2)' }}
              >
                {options.map(([k]) => k).join(' / ')}
              </span>
              <span>Option buttons double as keyboard shortcuts. Shortcuts pause while you type in the note.</span>
            </div>
          </>
        ) : (
          <div style={{ display: 'flex', gap: 10, alignItems: 'flex-end', flexWrap: 'wrap' }}>
            <textarea
              rows={2}
              placeholder="Type your answer"
              value={freeText}
              onChange={(e) => setFreeText(e.target.value)}
              disabled={isPending}
              style={{
                flex: 1,
                minWidth: 240,
                resize: 'vertical',
                border: '1px solid var(--line2)',
                background: 'var(--bg)',
                color: 'var(--ink)',
                padding: '10px 12px',
                font: "400 14px/1.5 'IBM Plex Sans',sans-serif",
              }}
            />
            <LoadingButton
              isLoading={isPending && pendingKey === '__freetext__'}
              disabled={isPending || !freeText.trim()}
              onClick={() => {
                const val = freeText.trim()
                if (!val) return
                onAnswerFreeText(val, who)
                setFreeText('')
              }}
            >
              Submit
            </LoadingButton>
          </div>
        )}
      </div>
    </section>
  )
}

function AgentOutputFeed({
  vi,
  vStatus,
  turns,
}: {
  vi: number
  vStatus: StageStatus
  turns: Turn[]
}) {
  const feedTurns = turns.filter((t) => turnStageIndex(t) === vi)
  const working = vStatus === 'running'

  return (
    <section>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 10 }}>
        <div className="mono" style={{ fontSize: 12, fontWeight: 600, letterSpacing: '.14em', textTransform: 'uppercase', color: 'var(--ink2)' }}>
          Agent output
        </div>
        <div className="mono" style={{ fontSize: 12, color: 'var(--muted)' }}>
          {feedTurns.length} messages
        </div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {working && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '14px 18px', border: '1px dashed var(--line2)', color: 'var(--ink2)' }}>
            <StatusMark status="running" />
            <span>
              <span className="mono" style={{ fontSize: 13, color: 'var(--ink)' }}>
                {STAGE_AGENT_IDS[vi][0]}
              </span>{' '}
              is working&hellip;
            </span>
          </div>
        )}
        {feedTurns.length === 0 && !working && (
          <div style={{ padding: 28, border: '1px dashed var(--line2)', color: 'var(--muted)', textAlign: 'center' }}>
            No output yet. This stage has not started.
          </div>
        )}
        {feedTurns
          .slice()
          .reverse()
          .map((f, idx) => (
            <article key={idx} className="card lds-in" style={{ display: 'grid', gridTemplateColumns: '36px minmax(0,1fr)', gap: 14, padding: '16px 18px' }}>
              <div
                style={{
                  width: 36,
                  height: 36,
                  border: '1px solid var(--line2)',
                  background: 'var(--surface2)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  font: "600 12px 'IBM Plex Mono',monospace",
                }}
              >
                {AGENT_INITIALS[baseAgentId(f.agent)] || '??'}
              </div>
              <div style={{ minWidth: 0 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'baseline' }}>
                  <span className="mono" style={{ fontSize: 13, fontWeight: 600 }}>
                    {f.agent}
                  </span>
                  <span className="mono" style={{ fontSize: 12, color: 'var(--muted)' }}>
                    {formatTime(f.created_at)}
                  </span>
                </div>
                <MarkdownRenderer text={f.text} />
              </div>
            </article>
          ))}
      </div>
    </section>
  )
}
