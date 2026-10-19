import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import type { AgentsResponse } from '../types'

export function useAgents(sid: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ['agents', sid],
    queryFn: () => api<AgentsResponse>(`/api/sessions/${sid}/agents`),
    enabled: !!sid && enabled,
  })
}
