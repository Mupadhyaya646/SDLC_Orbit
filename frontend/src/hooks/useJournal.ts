import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import type { JournalResponse } from '../types'

export function useJournal(sid: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ['journal', sid],
    queryFn: () => api<JournalResponse>(`/api/sessions/${sid}/journal`),
    enabled: !!sid && enabled,
  })
}
