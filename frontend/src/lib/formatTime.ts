export function formatTime(iso: string | null | undefined): string {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleTimeString('en-GB')
  } catch {
    return ''
  }
}
