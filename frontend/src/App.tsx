import { useSessionUi } from './state/SessionContext'
import { TurnsProvider } from './state/TurnsContext'
import { Header } from './components/layout/Header'
import { SessionTab } from './components/session/SessionTab'
import { PipelineTab } from './components/pipeline/PipelineTab'
import { AgentsTab } from './components/agents/AgentsTab'
import { LogTab } from './components/log/LogTab'
import { JournalTab } from './components/journal/JournalTab'

function MainContent() {
  const { tab } = useSessionUi()
  if (tab === 'session') return <SessionTab />
  if (tab === 'pipeline') return <PipelineTab />
  if (tab === 'agents') return <AgentsTab />
  if (tab === 'log') return <LogTab />
  return <JournalTab />
}

export default function App() {
  const { sid } = useSessionUi()
  return (
    <TurnsProvider sid={sid}>
      <div id="app">
        <Header />
        <main>
          <MainContent />
        </main>
      </div>
    </TurnsProvider>
  )
}
