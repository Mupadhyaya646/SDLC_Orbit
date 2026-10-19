export class ApiError extends Error {}

export async function api<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) }
  const r = await fetch(path, { ...opts, headers })
  let j: Record<string, unknown> = {}
  try {
    j = await r.json()
  } catch {
    j = {}
  }
  if (!r.ok) {
    const message = (j.detail as string) || (j.error as string) || `HTTP ${r.status}`
    throw new ApiError(message)
  }
  return j as T
}
