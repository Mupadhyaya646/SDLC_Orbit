import { useMutation } from '@tanstack/react-query'
import { api } from '../api'
import type { CreateSessionRequest, CreateSessionResponse } from '../types'

export function useStartSession() {
  return useMutation({
    mutationFn: (body: CreateSessionRequest) =>
      api<CreateSessionResponse>('/api/sessions', { method: 'POST', body: JSON.stringify(body) }),
  })
}
