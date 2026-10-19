import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import type { LogResponse } from '../types'

export function useLog(sid: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ['log', sid],
    queryFn: () => api<LogResponse>(`/api/sessions/${sid}/log`),
    enabled: !!sid && enabled,
  })
}
