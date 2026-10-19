import { useSessionUi, type Tab } from '../../state/SessionContext'
import { useTurns } from '../../state/TurnsContext'
import { useSession } from '../../hooks/useSession'
import { useLog } from '../../hooks/useLog'
import { useJournal } from '../../hooks/useJournal'
import { headerStatus, stageIndexFromState } from '../../lib/stageDerivation'
import { StatusMark } from '../shared/StatusMark'
import { ThemeToggle } from '../shared/ThemeToggle'

const TAB_LABELS: Array<[Tab, string]> = [
  ['session', 'Session'],
  ['pipeline', 'Pipeline'],
  ['agents', 'Agents'],
  ['log', 'Log'],
  ['journal', 'Journal'],
]

export function Tabs() {
  const { tab, setTab, sid } = useSessionUi()
  const { data: session } = useSession(sid)
  const { data: logData } = useLog(sid, tab === 'log')
  const { data: journalData } = useJournal(sid, tab === 'journal')

  const badges: Record<Tab, number> = {
    session: 0,
    pipeline: session?.status === 'awaiting_input' ? 1 : 0,
    agents: 0,
    log: logData?.entries.length ?? 0,
    journal: journalData?.entries.length ?? 0,
  }

  return (
    <nav className="tabs">
      {TAB_LABELS.map(([key, label]) => {
        const n = badges[key]
        return (
          <button key={key} className={'tab-btn' + (tab === key ? ' active' : '')} onClick={() => setTab(key)}>
            <span>{label}</span>
            {n > 0 && <span className={'tab-badge' + (key === 'pipeline' ? ' pipeline' : '')}>{n}</span>}
          </button>
        )
      })}
    </nav>
  )
}

export function Header() {
  const { sid, setTab, setSelected } = useSessionUi()
  const { data: session } = useSession(sid)
  const { connectionStatus } = useTurns()
  const hs = headerStatus(session ?? null)

  const onStatusClick = () => {
    if (hs.s !== 'awaiting' || !session?.pipeline_state) return
    setSelected(stageIndexFromState(session.pipeline_state))
    setTab('pipeline')
  }

  return (
    <header className="top sticky" id="appHeader">
      <div className="header-inner">
        <div className="header-row1">
          <div className="brand-left">
            <img src="/assets/lilly-logo.png" alt="Lilly" />
            <div className="brand-div" />
            <div>
              <div className="brand-title">SDLC_Orbit</div>
              <div className="brand-tag">AI agent pipeline for Salesforce changes, with a human at every decision</div>
            </div>
          </div>
          <div className="header-controls">
            <button
              className={'ctl' + (hs.s === 'awaiting' ? ' btn awaiting' : '')}
              onClick={hs.s === 'awaiting' ? onStatusClick : undefined}
            >
              <StatusMark status={hs.s} />
              <span style={{ fontWeight: 500 }}>{hs.l}</span>
            </button>
            <div className="ctl">
              <span className="dot" style={{ background: connectionStatus === 'connected' ? 'var(--green)' : 'var(--red)' }} />
              <span>{connectionStatus === 'connected' ? 'Connected' : 'Reconnecting'}</span>
            </div>
            <ThemeToggle />
          </div>
        </div>
        <Tabs />
      </div>
    </header>
  )
}
