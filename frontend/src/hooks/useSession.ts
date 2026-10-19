import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import type { Session } from '../types'

// 8s, not a tighter interval: the ALB in front of the deployed app
// re-validates its AD-group auth session periodically, and any request
// landing in that brief window gets the platform gateway's own 404 page
// instead of reaching this backend (observed live on the deployed dashboard).
// A slower poll means fewer requests overall, so fewer chances to land in
// that window. Ported from the vanilla-JS frontend's pollSession() comment --
// do not "optimize" this back down without re-confirming that constraint.
const SESSION_POLL_INTERVAL_MS = 8000

export function useSession(sid: string | null) {
  return useQuery({
    queryKey: ['session', sid],
    queryFn: () => api<Session>(`/api/sessions/${sid}`),
    enabled: !!sid,
    refetchInterval: SESSION_POLL_INTERVAL_MS,
  })
}
