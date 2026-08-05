<!-- JQL Search (epic #297, issue #302) — the "issue navigator" GitLab lacks.
     A query box over POST /api/query: type a JQL expression, get the live
     work items back in a sortable table. Parse errors render inline with a
     caret anchored at the reported position; header clicks re-sort the
     fetched rows client-side (the query's ORDER BY still defines fetch
     order), with a "sorted locally" hint when the limit truncated the set so
     a header sort isn't mistaken for a true top-N by that column. -->
<template>
  <div class="search-page">

    <header class="search-bar">
      <router-link class="back-link" to="/">← Simulator</router-link>
      <span class="search-title">JQL Search</span>
      <span class="search-sub">live query against
        <code v-if="groupPath" class="scope-slug">{{ groupPath }}</code>
        <template v-else>the configured GitLab group</template>
      </span>
    </header>

    <form class="query-form" @submit.prevent="run">
      <textarea
        v-if="expanded"
        v-model="query"
        class="query-input query-textarea"
        rows="4"
        spellcheck="false"
        autocomplete="off"
        placeholder='state = opened AND weight >= 5 ORDER BY due ASC'
        aria-label="JQL query"
        @keydown.ctrl.enter.prevent="run"
        @keydown.meta.enter.prevent="run"
      ></textarea>
      <input
        v-else
        v-model="query"
        class="query-input"
        type="text"
        spellcheck="false"
        autocomplete="off"
        placeholder='state = opened AND weight >= 5 ORDER BY due ASC'
        aria-label="JQL query"
      />
      <label class="limit-label">
        limit
        <input v-model.number="limit" class="limit-input" type="number" min="1" step="1" />
      </label>
      <button class="run-btn" type="submit" :disabled="state === 'loading'">Run</button>
      <button class="icon-btn expand-btn" type="button"
              :title="expanded ? 'Collapse query editor' : 'Expand query editor (multi-line)'"
              :aria-label="expanded ? 'Collapse query editor' : 'Expand query editor'"
              @click="expanded = !expanded">{{ expanded ? '⤒' : '⤓' }}</button>
      <button class="icon-btn help-btn" type="button" title="JQL syntax help"
              aria-label="JQL syntax help" :class="{ active: showHelp }"
              @click="toggleHelp">?</button>
    </form>

    <!-- ── Syntax help: reference + examples built from the live vocabulary ── -->
    <section v-if="showHelp" class="help-panel" aria-label="JQL help">
      <div class="help-head">
        <span class="help-title">JQL against GitLab — syntax &amp; examples</span>
        <span v-if="groupPath" class="help-scope">queries run against <code class="scope-slug">{{ groupPath }}</code></span>
        <button class="icon-btn help-close" type="button" aria-label="Close help" @click="showHelp = false">✕</button>
      </div>

      <div class="help-grid">
        <div class="help-block">
          <h3>Operators</h3>
          <table class="help-table">
            <tbody>
              <tr><td><code>=</code> <code>!=</code></td><td>equality (case-insensitive)</td></tr>
              <tr><td><code>&gt;</code> <code>&gt;=</code> <code>&lt;</code> <code>&lt;=</code></td><td>numbers and dates</td></tr>
              <tr><td><code>~</code> <code>!~</code></td><td>substring match (<code>title</code>, <code>text</code>, …)</td></tr>
              <tr><td><code>IN (a, b)</code> <code>NOT IN</code></td><td>any-of / none-of a value list</td></tr>
              <tr><td><code>IS EMPTY</code> <code>IS NOT EMPTY</code></td><td>unset / set (<code>assignee</code>, <code>due</code>, …)</td></tr>
              <tr><td><code>AND</code> <code>OR</code> <code>NOT</code> <code>( )</code></td><td>boolean logic, any nesting</td></tr>
              <tr><td><code>ORDER BY f ASC, g DESC</code></td><td>multi-key ordering, trailing</td></tr>
            </tbody>
          </table>
        </div>
        <div class="help-block">
          <h3>Dates</h3>
          <table class="help-table">
            <tbody>
              <tr><td><code>"2026-08-01"</code></td><td>absolute date</td></tr>
              <tr><td><code>-4w</code> <code>12h</code> <code>-90d</code></td><td>relative to now (m/h/d/w)</td></tr>
              <tr><td><code>now()</code> <code>currentUser()</code></td><td>evaluation-time values</td></tr>
              <tr><td><code>startOfDay()</code> <code>endOfWeek()</code></td><td>also <code>…OfMonth</code>/<code>…OfYear</code></td></tr>
              <tr><td><code>startOfMonth(-1)</code></td><td>offset in the unit (last month)</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="help-block">
        <h3>Fields</h3>
        <p class="help-note">Canonical names with Jira aliases in parentheses; taxonomy fields list the exact values valid <em>in this group's config</em>.</p>
        <div class="help-fields-wrap">
          <table class="help-table help-fields" v-if="fields.length">
            <thead><tr><th>field</th><th>type</th><th>values</th></tr></thead>
            <tbody>
              <tr v-for="f in fields" :key="f.name">
                <td><code>{{ f.name }}</code><span v-if="f.aliases.length" class="alias"> ({{ f.aliases.join(', ') }})</span></td>
                <td>{{ f.type }}</td>
                <td class="cell-values"><template v-if="f.values.length"><code v-for="v in f.values" :key="v" class="value-chip">{{ v }}</code></template><span v-else>—</span></td>
              </tr>
            </tbody>
          </table>
          <p v-else class="help-note">Loading field vocabulary…</p>
        </div>
      </div>

      <div class="help-block">
        <h3>Examples</h3>
        <p class="help-note">Built from this group's live configuration — click one to run it, or copy it for the CLI / <code>POST /api/query</code>.</p>
        <ol class="help-examples">
          <li v-for="section in exampleSections" :key="section.title">
            <span class="example-section">{{ section.title }}</span>
            <ol>
              <li v-for="ex in section.items" :key="ex">
                <button class="example-btn" type="button" :title="'Run: ' + ex" @click="query = ex; showHelp = false; run()">{{ ex }}</button>
                <button class="icon-btn copy-btn" type="button" :aria-label="'Copy: ' + ex" title="Copy" @click="copyText(ex)">⧉</button>
              </li>
            </ol>
          </li>
        </ol>
      </div>
    </section>

    <!-- ── Inline query errors ── -->
    <div v-if="state === 'error' && syntaxError" class="error-box">
      <div class="error-lead">Syntax error</div>
      <pre class="error-query">{{ lastQuery }}
{{ caretLine }}</pre>
      <div class="error-msg">{{ error.message }}</div>
      <div v-if="error.detail.expected && error.detail.expected.length" class="error-expected">
        expected: <code v-for="e in error.detail.expected" :key="e">{{ e }}</code>
      </div>
    </div>
    <div v-else-if="state === 'error'" class="error-box">
      <div class="error-lead">{{ errorLead }}</div>
      <div class="error-msg">{{ error.message }}</div>
    </div>

    <!-- ── Empty / loading / results ── -->
    <div v-if="state === 'idle'" class="search-empty">
      <p class="empty-lead">Query the portfolio with JQL</p>
      <p>Fields include <code>type</code>, <code>state</code>, <code>labels</code>, <code>assignee</code>, <code>weight</code>, <code>piid</code>, <code>epic_type</code>, <code>business_value</code>, dates… Try one:</p>
      <ul class="example-list">
        <li v-for="ex in EXAMPLES" :key="ex">
          <button class="example-btn" type="button" @click="query = ex; run()">{{ ex }}</button>
        </li>
      </ul>
    </div>

    <div v-else-if="state === 'loading'" class="search-empty">Running query…</div>

    <template v-else-if="state === 'ready'">
      <div class="results-meta">
        <span>{{ result.count }} result{{ result.count === 1 ? '' : 's' }}</span>
        <span v-if="result.truncated" class="meta-truncated">capped at limit {{ result.limit }} — more may match</span>
        <span v-if="localSort && result.truncated" class="meta-hint">
          sorted locally — first {{ result.count }} results only, not a true top-{{ result.count }} by this column
        </span>
        <button v-if="localSort" class="meta-reset" type="button" @click="localSort = null">reset to query order</button>
      </div>

      <div v-if="!result.count" class="search-empty">
        <p class="empty-lead">No matching work items</p>
        <p>The query ran fine — nothing in the group matches it.</p>
      </div>

      <div v-else class="table-wrap">
        <table class="results-table">
          <thead>
            <tr>
              <th
                v-for="col in COLUMNS" :key="col.key"
                :aria-sort="ariaSort(col.key)"
              >
                <button class="th-btn" type="button" :title="`Sort by ${col.label}`" @click="toggleSort(col.key)">
                  {{ col.label }}
                  <span v-if="localSort && localSort.key === col.key" class="sort-arrow">{{ localSort.dir === 'asc' ? '▲' : '▼' }}</span>
                </button>
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in displayRows" :key="row.id">
              <td class="cell-num">{{ row.iid }}</td>
              <td class="cell-title">
                <a :href="row.web_url" target="_blank" rel="noopener" :title="row.title">{{ row.title }}</a>
              </td>
              <td class="cell-type">{{ row.type }}</td>
              <td><span class="state-chip" :class="row.state">{{ row.state }}</span></td>
              <td class="cell-labels">
                <span v-for="l in row.labels" :key="l" class="label-chip">{{ l }}</span>
              </td>
              <td class="cell-num">{{ row.weight ?? '—' }}</td>
              <td class="cell-people">{{ row.assignees.length ? row.assignees.join(', ') : '—' }}</td>
              <td class="cell-date">{{ day(row.created_at) }}</td>
              <td class="cell-date">{{ day(row.updated_at) }}</td>
              <td class="cell-date">{{ day(row.due_date) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>

  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { getConfig, getQueryFields, postQuery } from '../api.js'

// Column set per the issue #302 spec: title, type, state, labels, weight,
// assignees, dates, link. (Wider than the CLI `table` output on purpose —
// both surfaces fetch identical rows through run_jql; only the columns
// rendered differ.)
const COLUMNS = [
  { key: 'iid',        label: 'IID',       kind: 'number' },
  { key: 'title',      label: 'Title',     kind: 'text' },
  { key: 'type',       label: 'Type',      kind: 'text' },
  { key: 'state',      label: 'State',     kind: 'text' },
  { key: 'labels',     label: 'Labels',    kind: 'list' },
  { key: 'weight',     label: 'Weight',    kind: 'number' },
  { key: 'assignees',  label: 'Assignees', kind: 'list' },
  { key: 'created_at', label: 'Created',   kind: 'date' },
  { key: 'updated_at', label: 'Updated',   kind: 'date' },
  { key: 'due_date',   label: 'Due',       kind: 'date' },
]

const EXAMPLES = [
  'state = opened AND weight >= 5 ORDER BY due ASC',
  'type = epic AND labels = "epic::feature"',
  'assignee = currentUser() AND updated >= -4w',
  'state = opened AND (assignee IS EMPTY OR due < startOfDay())',
  'business_value >= 8 ORDER BY business_value DESC, weight DESC',
]

// The exact group slug the engine queries — so the scope is unambiguous
// (the portfolio group from config.json, not the whole GitLab instance).
const groupPath = ref('')
onMounted(async () => { groupPath.value = (await getConfig()).target_group_path || '' })

// ── Help panel + expandable editor (Jira-search-bar affordances) ──
const expanded = ref(false)     // single-line input ⇄ multi-line textarea
const showHelp = ref(false)
const fields   = ref([])        // live vocabulary from /api/query/fields

async function toggleHelp() {
  showHelp.value = !showHelp.value
  if (showHelp.value && !fields.value.length) {
    fields.value = await getQueryFields()
  }
}

function copyText(text) {
  try { navigator.clipboard.writeText(text) } catch { /* clipboard denied — copy manually */ }
}

// Examples assembled from the group's real taxonomy values, so pasting one
// returns real data from the configured scope — not vocabulary that only
// exists in documentation.
const quoteVal = v => (/^[A-Za-z0-9_.-]+$/.test(v) ? v : `"${v}"`)
const exampleSections = computed(() => {
  const byName = Object.fromEntries(fields.value.map(f => [f.name, f]))
  const val  = (name, i = 0) => {
    const f = byName[name]
    return f && f.values.length > i ? quoteVal(f.values[i]) : null
  }
  const sections = []
  sections.push({ title: 'Basics', items: [
    'state = opened',
    'type = epic AND state = opened',
    'weight >= 8 ORDER BY weight DESC',
  ]})
  const tax = []
  for (const name of ['piid', 'epic_type', 'project_label', 'lifecycle',
                      'work_type', 'risk', 'wsjf_urgency']) {
    const v = val(name)
    if (v) tax.push(`${name} = ${v} AND state = opened`)
  }
  const p0 = val('piid'), p1 = val('piid', 1)
  if (p0 && p1) tax.push(`piid IN (${p0}, ${p1}) ORDER BY weight DESC`)
  if (tax.length) sections.push({ title: 'SAFe taxonomy (this group’s values)', items: tax })
  sections.push({ title: 'Dates and functions', items: [
    'updated >= -4w',
    'due <= endOfYear() AND state = opened',
    'created >= startOfMonth(-1) AND created < startOfMonth()',
  ]})
  sections.push({ title: 'People and empties', items: [
    'assignee = currentUser() AND state = opened',
    'assignee IS EMPTY AND due < startOfDay()',
  ]})
  sections.push({ title: 'Text and Jira aliases', items: [
    'text ~ "readiness" ORDER BY updated DESC',
    'status = opened AND issuetype = epic',      // Jira names alias to GitLab fields
  ]})
  if (byName.business_value) sections.push({ title: 'Business value', items: [
    'business_value >= 8 ORDER BY business_value DESC, weight DESC',
  ]})
  return sections
})

const query     = ref('')
const limit     = ref(100)
const state     = ref('idle')   // idle | loading | ready | error
const result    = ref(null)
const error     = ref(null)
const lastQuery = ref('')       // the exact string the error position anchors to
const localSort = ref(null)     // { key, dir } — client-side re-sort of fetched rows

const syntaxError = computed(() =>
  error.value && error.value.detail && error.value.detail.kind === 'syntax'
  && Number.isInteger(error.value.detail.position))

const caretLine = computed(() =>
  syntaxError.value ? ' '.repeat(error.value.detail.position) + '^' : '')

const errorLead = computed(() => {
  const kind = error.value && error.value.detail && error.value.detail.kind
  if (kind === 'semantic')    return 'Query error'
  if (kind === 'transport')   return 'GitLab unreachable'
  if (kind === 'unavailable') return 'Server has no GitLab connection'
  return 'Query failed'
})

async function run() {
  state.value     = 'loading'
  error.value     = null
  localSort.value = null        // a fresh fetch renders in query order
  lastQuery.value = query.value
  try {
    const lim = Number.isInteger(limit.value) && limit.value > 0 ? limit.value : undefined
    result.value = await postQuery(query.value, lim)
    state.value  = 'ready'
  } catch (e) {
    error.value = e
    state.value = 'error'
  }
}

// ── Client-side header sorting — a re-sort of the fetched rows only; the
//    query's ORDER BY still defines the fetch order. No new API call. ──
function toggleSort(key) {
  if (localSort.value && localSort.value.key === key) {
    localSort.value = { key, dir: localSort.value.dir === 'asc' ? 'desc' : 'asc' }
  } else {
    localSort.value = { key, dir: 'asc' }
  }
}

function ariaSort(key) {
  if (!localSort.value || localSort.value.key !== key) return 'none'
  return localSort.value.dir === 'asc' ? 'ascending' : 'descending'
}

function sortValue(row, col) {
  const v = row[col.key]
  if (v == null) return null
  if (col.kind === 'list')   return v.length ? v.join(', ').toLowerCase() : null
  if (col.kind === 'number') return typeof v === 'number' ? v : Number(v)
  if (col.kind === 'date')   return v            // ISO-8601 sorts lexicographically
  return String(v).toLowerCase()
}

const displayRows = computed(() => {
  const rows = result.value ? [...result.value.items] : []
  const sort = localSort.value
  if (!sort) return rows
  const col = COLUMNS.find(c => c.key === sort.key)
  const dirMul = sort.dir === 'asc' ? 1 : -1
  // Stable sort, empties last in either direction.
  return rows.sort((a, b) => {
    const va = sortValue(a, col)
    const vb = sortValue(b, col)
    if (va == null && vb == null) return 0
    if (va == null) return 1
    if (vb == null) return -1
    if (va < vb) return -1 * dirMul
    if (va > vb) return  1 * dirMul
    return 0
  })
})

function day(iso) {
  return iso ? String(iso).slice(0, 10) : '—'
}
</script>

<style scoped>
.search-page {
  height: 100vh;
  height: 100dvh;
  display: flex;
  flex-direction: column;
  background: var(--bg);
}

/* ── Top bar ── */
.search-bar {
  flex-shrink: 0;
  display: flex;
  align-items: baseline;
  gap: 0.75rem;
  padding: 0.65rem 1.25rem;
  border-bottom: 2px solid rgba(252, 109, 38, 0.25);
  background: var(--surface);
}
.back-link {
  color: var(--action);
  text-decoration: none;
  font-size: 0.85rem;
  white-space: nowrap;
}
.back-link:hover { text-decoration: underline; }
.search-title { font-size: 0.95rem; font-weight: 600; color: var(--text-1); }
.search-sub   { font-size: 0.75rem; color: var(--text-3); }
.scope-slug   { font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
                font-size: 0.72rem; color: var(--text-2); }

/* ── Query form ── */
.query-form {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.75rem 1.25rem;
  border-bottom: 1px solid var(--border);
}
.query-input {
  flex: 1;
  min-width: 0;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text-1);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.85rem;
  padding: 0.5rem 0.7rem;
}
.query-input:focus { outline: none; border-color: var(--action); }
.limit-label {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.75rem;
  color: var(--text-3);
  white-space: nowrap;
}
.limit-input {
  width: 5.5rem;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text-1);
  font-size: 0.82rem;
  padding: 0.45rem 0.5rem;
  font-variant-numeric: tabular-nums;
}
.run-btn {
  background: var(--action);
  border: none;
  border-radius: 6px;
  color: #fff;
  font-size: 0.85rem;
  font-weight: 600;
  padding: 0.5rem 1.1rem;
  cursor: pointer;
}
.run-btn:disabled { opacity: 0.6; cursor: default; }

/* ── Search-bar affordances: expand editor + help (Jira-style, far right) ── */
.icon-btn {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text-2);
  cursor: pointer;
  font-size: 0.85rem;
  line-height: 1;
  padding: 0.5rem 0.6rem;
}
.icon-btn:hover, .icon-btn.active { border-color: var(--action); color: var(--action); }
.query-textarea {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  resize: vertical;
  min-height: 4.5rem;
}

/* ── Help panel ── */
.help-panel {
  flex-shrink: 0;
  margin: 0.75rem 1.25rem 0;
  padding: 0.9rem 1.1rem;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow-y: auto;
  max-height: 60vh;
  font-size: 0.8rem;
}
.help-head {
  display: flex;
  align-items: baseline;
  gap: 0.8rem;
  margin-bottom: 0.6rem;
}
.help-title { font-weight: 600; color: var(--text-1); }
.help-scope { font-size: 0.75rem; color: var(--text-3); }
.help-close { margin-left: auto; padding: 0.25rem 0.5rem; }
.help-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 0.5rem 1.5rem;
}
.help-block h3 {
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-3);
  margin: 0.7rem 0 0.3rem;
}
.help-note { color: var(--text-3); margin: 0.1rem 0 0.4rem; }
.help-table { border-collapse: collapse; }
.help-table td, .help-table th {
  padding: 0.15rem 0.9rem 0.15rem 0;
  text-align: left;
  vertical-align: top;
  color: var(--text-2);
}
.help-table th { font-size: 0.7rem; color: var(--text-3); font-weight: 600; }
.help-table code {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.75rem;
  color: var(--text-1);
}
.help-fields-wrap { overflow-x: auto; }
.help-fields .alias { color: var(--text-3); font-size: 0.72rem; }
.cell-values { max-width: 34rem; }
.value-chip {
  display: inline-block;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 0 0.3rem;
  margin: 0.08rem 0.25rem 0.08rem 0;
}
.help-examples { margin: 0.2rem 0 0; padding-left: 1.1rem; }
.help-examples > li { margin-bottom: 0.5rem; }
.help-examples ol { list-style: decimal; padding-left: 1.3rem; margin: 0.2rem 0; }
.help-examples ol li { margin: 0.22rem 0; }
.example-section { font-weight: 600; color: var(--text-2); }
.copy-btn { font-size: 0.72rem; padding: 0.18rem 0.4rem; margin-left: 0.4rem; }

/* ── Inline errors ── */
.error-box {
  flex-shrink: 0;
  margin: 0.85rem 1.25rem 0;
  border: 1px solid rgba(248, 81, 73, 0.5);
  border-radius: 6px;
  background: rgba(248, 81, 73, 0.07);
  padding: 0.65rem 0.9rem;
  font-size: 0.82rem;
  color: var(--text-2);
}
.error-lead {
  font-weight: 700;
  color: #f85149;
  font-size: 0.74rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 0.35rem;
}
.error-query {
  margin: 0 0 0.4rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.82rem;
  line-height: 1.35;
  color: var(--text-1);
  white-space: pre;
  overflow-x: auto;
}
.error-msg { line-height: 1.45; }
.error-expected { margin-top: 0.35rem; color: var(--text-3); }
.error-expected code {
  background: var(--surface-alt);
  border: 1px solid var(--border);
  border-radius: 3px;
  padding: 0 0.3rem;
  margin-right: 0.3rem;
  font-size: 0.76rem;
  color: var(--text-2);
}

/* ── Empty / loading states ── */
.search-empty {
  padding: 2.5rem 1.5rem;
  text-align: center;
  color: var(--text-3);
  font-size: 0.85rem;
  line-height: 1.6;
}
.empty-lead { font-size: 1rem; font-weight: 600; color: var(--text-2); margin: 0 0 0.3rem; }
.search-empty code {
  background: var(--surface-alt);
  border: 1px solid var(--border);
  border-radius: 3px;
  padding: 0 0.3rem;
  font-size: 0.78rem;
}
.example-list {
  list-style: none;
  margin: 0.8rem 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  align-items: center;
}
.example-btn {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--action);
  cursor: pointer;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.78rem;
  padding: 0.3rem 0.7rem;
}
.example-btn:hover { border-color: var(--action); }

/* ── Results ── */
.results-meta {
  flex-shrink: 0;
  display: flex;
  align-items: baseline;
  gap: 0.8rem;
  flex-wrap: wrap;
  padding: 0.55rem 1.25rem;
  font-size: 0.76rem;
  color: var(--text-2);
}
.meta-truncated { color: #d29922; }
.meta-hint {
  color: #d29922;
  background: rgba(210, 153, 34, 0.1);
  border: 1px solid rgba(210, 153, 34, 0.35);
  border-radius: 4px;
  padding: 0.05rem 0.5rem;
}
.meta-reset {
  background: none;
  border: none;
  color: var(--action);
  cursor: pointer;
  font-size: 0.76rem;
  padding: 0;
}
.meta-reset:hover { text-decoration: underline; }

.table-wrap {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 0 1.25rem 1.25rem;
}
.results-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.8rem;
}
.results-table th {
  position: sticky;
  top: 0;
  z-index: 1;
  background: var(--surface);
  border-bottom: 2px solid var(--border);
  padding: 0;
  text-align: left;
  white-space: nowrap;
}
.th-btn {
  width: 100%;
  background: none;
  border: none;
  color: var(--text-2);
  cursor: pointer;
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  text-align: left;
  padding: 0.45rem 0.6rem;
}
.th-btn:hover { color: var(--text-1); }
.sort-arrow { color: var(--action); font-size: 0.65rem; }
.results-table td {
  border-bottom: 1px solid var(--border);
  padding: 0.4rem 0.6rem;
  vertical-align: top;
  color: var(--text-2);
}
.cell-num  { font-variant-numeric: tabular-nums; white-space: nowrap; }
.cell-date { font-variant-numeric: tabular-nums; white-space: nowrap; color: var(--text-3); }
.cell-type { white-space: nowrap; }
.cell-title { min-width: 16rem; }
.cell-title a { color: var(--text-1); text-decoration: none; font-weight: 600; }
.cell-title a:hover { color: var(--action); text-decoration: underline; }
.cell-people { white-space: nowrap; }
.state-chip {
  font-size: 0.68rem;
  font-weight: 700;
  border-radius: 999px;
  padding: 0.06rem 0.5rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.state-chip.opened { background: rgba(63, 185, 80, 0.14); color: #3fb950; }
.state-chip.closed { background: var(--surface-alt); color: var(--text-3); }
.cell-labels { max-width: 18rem; }
.label-chip {
  display: inline-block;
  font-size: 0.66rem;
  font-weight: 600;
  background: var(--surface-alt);
  border: 1px solid var(--border);
  color: var(--text-2);
  border-radius: 999px;
  padding: 0.03rem 0.45rem;
  margin: 0.08rem 0.25rem 0.08rem 0;
  white-space: nowrap;
}

/* ── Mobile ── */
@media (max-width: 768px) {
  .search-bar, .query-form, .results-meta { padding-left: 0.75rem; padding-right: 0.75rem; }
  .search-sub { display: none; }
  .query-form { flex-wrap: wrap; }
  .query-input { flex-basis: 100%; }
  .table-wrap { padding: 0 0.75rem 0.75rem; }
}
</style>
