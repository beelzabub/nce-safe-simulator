// Build the equivalent `NceGitLab.py` command line for an operation the user is
// about to launch from the web UI (issue #140).
//
// The CLI accepts operations non-interactively: after `-ut <tool-key>` (tools)
// or `-r <report>` (reports), extra `--param value` / `--flag` tokens are parsed
// into prefills (NceGitLab.py:_parse_tool_args) and applied without prompting.
// So the values already collected in a dialog map straight to a runnable command.
//
// These are pure functions (no Vue reactivity) so they can be unit-reasoned and
// reused across the tool dialog, the report picker, and the docked CommandBar.
// IMPORTANT: keep this module dependency-free (no `vue` import) — the contract
// test (tests/test_cli_command_preview.py) imports it verbatim into bare Node.
// The reactive command-preview state lives in useCommandPreview.js.

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
// falls back to its own default / prompt).
function _isSet(value) {
  return value !== null && value !== undefined && value !== ''
}

// Emit a `--name value` pair, choosing the attached `--name=value` form when the
// value begins with '-'. The bare form would let the CLI parser mistake a
// dash-leading value (e.g. a negative count) for the next flag and treat this
// flag as a valueless boolean; the attached form is unambiguous.
function _pushValue(tokens, name, value) {
  const q = shellQuote(value)
  if (String(value).startsWith('-')) tokens.push(`--${name}=${q}`)
  else tokens.push(`--${name}`, q)
}

// Build the token list (flags) for a tool's params from the dialog's values.
// `params` is the web tool payload's param list (cli_only params are already
// stripped from that payload, so nothing server-only leaks in).
export function toolArgTokens(params, values) {
  const tokens = []
  for (const p of params || []) {
    const v = values ? values[p.name] : undefined
    if (p.type === 'bool') {
      // Booleans are expressed relative to the param's default.
      //   default-off: presence turns it on, absence leaves it off (readable case).
      //   default-on:  stated explicitly either way — omitting it would drop to the
      //                CLI's own prompt/default (on) and, when turned off, reproduce
      //                the opposite value.
      if (v === undefined || v === null) continue
      const on = v === true
      if (p.default === true) {
        tokens.push(on ? `--${p.name}` : `--${p.name}=false`)
      } else if (on) {
        tokens.push(`--${p.name}`)
      }
      continue
    }
    if (!_isSet(v)) continue
    _pushValue(tokens, p.name, v)
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
