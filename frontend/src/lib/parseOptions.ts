// Parses "[A] Approve\n[C] Changes\n[X] Cancel" style gate text into
// option pairs, or detects "(yes/no/changes)" phrasing as a three-option
// fallback. Ported verbatim from the vanilla-JS frontend's parseOptions() --
// this regex is tuned against how the real agent prompts phrase their gates,
// not something to "clean up" without re-testing against live agent output.
export function parseOptions(text: string): Array<[string, string]> {
  const out: Array<[string, string]> = []
  const seen: Record<string, boolean> = {}
  const re = /\[([A-Za-z0-9]{1,3})\]\s*([^\n[]{0,70})/g
  let m: RegExpExecArray | null
  while ((m = re.exec(text))) {
    const k = m[1]
    if (!seen[k]) {
      seen[k] = true
      out.push([k, m[2].replace(/[—–-]\s*$/, '').trim()])
    }
  }
  if (out.length < 2 && /\(\s*yes\s*\/\s*no\s*\/\s*changes\s*\)/i.test(text)) {
    return [
      ['yes', 'Yes, proceed'],
      ['no', 'No'],
      ['changes', 'Changes...'],
    ]
  }
  return out.length >= 2 ? out.slice(0, 8) : []
}
