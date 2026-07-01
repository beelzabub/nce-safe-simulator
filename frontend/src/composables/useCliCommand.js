// Build the equivalent `NceGitLab.py` command line for an operation the user is
// about to launch from the web UI (issue #140).
//
// The CLI accepts operations non-interactively: after `-ut <tool-key>` (tools)
// or `-r <report>` (reports), extra `--param value` / `--flag` tokens are parsed
// into prefills (NceGitLab.py:_parse_tool_args) and applied without prompting.
// So the values already collected in a dialog map straight to a runnable command.
//
// These are pure functions (no Vue reactivity) so they can be unit-reasoned and
// reused across the tool dialog, the report picker, and per-action buttons.

export const CLI_ENTRY = 'python3 NceGitLab.py'

// Wrap a value for a POSIX shell only when it contains characters that would
// otherwise be split or interpreted. Safe, printable tokens are left bare so the
// common case (a tool key, a slug, a plain path) reads cleanly.
export function shellQuote(value) {
  const s = String(value)
  if (s === '') return "''"
  if (/^[A-Za-z0-9_@%+=:,./-]+$/.test(s)) return s
  // single-quote wrap; close-escape-reopen any embedded single quote
  return "'" + s.replace(/'/g, `'\\''`) + "'"
}

// Should this param value contribute a token to the command?
// A blank (null / undefined / '') optional means "not chosen" → omitted (the CLI
// falls back to its own default / prompt). A false boolean is omitted too: the
// CLI has no negative flag, and absence is how you express "off".
function _isSet(value) {
  return value !== null && value !== undefined && value !== ''
}

// Build the token list (flags) for a tool's params from the dialog's values.
// `params` is the web tool payload's param list (cli_only params are already
// stripped from that payload, so nothing server-only leaks in).
export function toolArgTokens(params, values) {
  const tokens = []
  for (const p of params || []) {
    const v = values ? values[p.name] : undefined
    if (p.type === 'bool') {
      if (v === true) tokens.push(`--${p.name}`)
      continue
    }
    if (!_isSet(v)) continue
    tokens.push(`--${p.name}`, shellQuote(v))
  }
  return tokens
}

// Full command string for a `-ut` tool launch.
export function buildToolCommand(tool, values) {
  if (!tool || !tool.key) return ''
  const parts = [CLI_ENTRY, '-ut', tool.key, ...toolArgTokens(tool.params, values)]
  return parts.join(' ')
}

// Full command(s) for a report launch. The CLI's `-r` takes a single report, so
// a multi-report selection becomes one line per report (shared formats / --last).
// `useLast` reuses the most recent data snapshot instead of fetching fresh.
export function buildReportCommand(reports, formats, useLast) {
  const list = (Array.isArray(reports) ? reports : [reports]).filter(Boolean)
  if (!list.length) return ''
  const tail = []
  if (formats && formats.length) tail.push('--formats', ...formats.map(shellQuote))
  if (useLast) tail.push('--last')
  const suffix = tail.length ? ' ' + tail.join(' ') : ''
  return list.map(r => `${CLI_ENTRY} -r ${shellQuote(r)}${suffix}`).join('\n')
}
