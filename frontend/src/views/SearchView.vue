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
      <span class="search-sub">live query against the configured GitLab group</span>
    </header>

    <form class="query-form" @submit.prevent="run">
      <input
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
    </form>

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
import { ref, computed } from 'vue'
import { postQuery } from '../api.js'

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
