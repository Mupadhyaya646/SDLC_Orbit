import type { StageStatus } from '../../types'

export function StatusMark({ status }: { status: StageStatus | 'idle' }) {
  if (status === 'done')
    return (
      <span className="statusmark">
        <span className="sm-done">
          <span />
        </span>
      </span>
    )
  if (status === 'awaiting')
    return (
      <span className="statusmark">
        <span className="sm-awaiting">!</span>
      </span>
    )
  if (status === 'running')
    return (
      <span className="statusmark">
        <span className="sm-running">
          <span className="ring" />
          <span className="dot2" />
        </span>
      </span>
    )
  if (status === 'failed')
    return (
      <span className="statusmark">
        <span className="sm-failed">&times;</span>
      </span>
    )
  return (
    <span className="statusmark">
      <span className="sm-idle" />
    </span>
  )
}
