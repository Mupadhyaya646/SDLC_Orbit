import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import type { ReplyRequest } from '../types'

export function useReplyToGate(sid: string | null) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: ReplyRequest) =>
      api<{ ok: true }>(`/api/sessions/${sid}/reply`, { method: 'POST', body: JSON.stringify(body) }),
    onSuccess: () => {
      // Refetch immediately rather than waiting for the next 8s session poll tick.
      queryClient.invalidateQueries({ queryKey: ['session', sid] })
    },
  })
}
