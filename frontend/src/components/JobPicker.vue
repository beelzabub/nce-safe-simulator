<template>
  <div class="picker">

    <!-- Filter bar -->
    <div class="picker-filter">
      <div class="filter-wrap">
        <input
          v-model="filter"
          class="filter-input"
          placeholder="Filter jobs…"
          spellcheck="false"
        />
        <button
          v-if="filter"
          class="filter-clear"
          @click="filter = ''"
          aria-label="Clear filter"
        >×</button>
      </div>
      <span v-if="!loading && !error" class="filter-count">
        {{ filteredCount }}&thinsp;/&thinsp;{{ tools.length }}
      </span>
    </div>

    <!-- States -->
    <div v-if="loading" class="state-msg">Loading…</div>
    <div v-else-if="error" class="state-msg state-error">{{ error }}</div>

    <!-- Groups -->
    <div v-else class="picker-body">
      <section
        v-for="[group, items] in visibleGroups"
        :key="group"
        class="group"
      >
        <button class="group-header" @click="toggleSection(group)">
          <span class="chevron">{{ isOpen(group) ? '▼' : '▶' }}</span>
          <span class="group-name">{{ formatGroup(group) }}</span>
          <span class="group-count">{{ items.length }}</span>
        </button>

        <ul v-if="isOpen(group)" class="group-items">
          <li
            v-for="t in items"
            :key="t.key"
            class="job-item"
            :class="{
              selected:    selected?.key === t.key && !t.params?.length,
              running:     isRunning(t.key),
              configurable: t.params?.length > 0,
            }"
            @click="handleClick(t)"
          >
            <div class="item-top">
              <span class="item-name">{{ formatKey(t.key) }}</span>
              <span v-if="isRunning(t.key)" class="badge badge-run">● running</span>
              <span v-else-if="t.readonly" class="badge badge-ro">read-only</span>
              <span v-else-if="t.params?.length" class="badge badge-cfg">configure ›</span>
            </div>
            <div class="item-desc">{{ t.description }}</div>
          </li>
        </ul>
      </section>

      <div v-if="visibleGroups.size === 0 && filter" class="state-msg">
        No jobs match "{{ filter }}"
      </div>
    </div>

    <!-- Launch area — pinned to bottom; only for no-param tools -->
    <div class="launch-area">
      <ConflictBanner :blockers="blockers" />
      <div class="launch-row">
        <span class="launch-selection" :class="{ dim: !selected }">
          {{ selected ? formatKey(selected.key) : 'Nothing selected' }}
        </span>
        <button
          class="launch-btn"
          :disabled="!selected || blockers.length > 0"
          @click="launch"
        >
          Launch
        </button>
      </div>
      <div class="reports-row">
        <button class="reports-btn" @click="showReportDialog = true">
          Run Reports…
        </button>
      </div>
    </div>

  </div>

  <!-- Parameter dialog -->
  <ToolParamDialog
    :tool="dialogTool"
    @launch="onDialogLaunch"
    @cancel="dialogTool = null"
  />

  <!-- Report picker dialog -->
  <ReportPickerDialog
    v-if="showReportDialog"
    :reports="reports"
    @launch="onReportLaunch"
    @close="showReportDialog = false"
  />
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { getTools, getReports } from '../api.js'
import ConflictBanner from './ConflictBanner.vue'
import ToolParamDialog from './ToolParamDialog.vue'
import ReportPickerDialog from './ReportPickerDialog.vue'

const props = defineProps({
  runningJobs: { type: Array, default: () => [] },
})
const emit = defineEmits(['launch', 'launch-reports'])

const tools          = ref([])
const reports        = ref([])
const selected       = ref(null)
const dialogTool     = ref(null)
const loading        = ref(true)
const error          = ref(null)
const filter         = ref('')
const expanded       = ref([])
const showReportDialog = ref(false)

onMounted(async () => {
  try {
    ;[tools.value, reports.value] = await Promise.all([getTools(), getReports()])
  } catch (e) {
    error.value = `Failed to load: ${e.message}`
  } finally {
    loading.value = false
  }
})

// ── Display helpers ───────────────────────────────────────────────────────

const ACRONYMS = new Set(['roam', 'wsjf', 'bv', 'piid', 'pi'])

function formatKey(key) {
  return key.split('-').map(w =>
    ACRONYMS.has(w.toLowerCase()) ? w.toUpperCase() : w[0].toUpperCase() + w.slice(1)
  ).join(' ')
}

function formatGroup(g) {
  if (g === 'read-only') return 'Read-only Tools'
  return g.split('-').map(w =>
    ACRONYMS.has(w.toLowerCase()) ? w.toUpperCase() : w[0].toUpperCase() + w.slice(1)
  ).join(' ')
}

// ── Grouping ──────────────────────────────────────────────────────────────

const groupedTools = computed(() => {
  const groups = new Map()
  for (const t of tools.value) {
    const key = t.readonly ? 'read-only' : (t.parallelism_group ?? 'other')
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key).push(t)
  }
  return new Map(
    [...groups.entries()].sort(([a], [b]) =>
      a === 'read-only' ? 1 : b === 'read-only' ? -1 : a.localeCompare(b)
    )
  )
})

const visibleGroups = computed(() => {
  const q = filter.value.toLowerCase().trim()
  if (!q) return groupedTools.value
  const result = new Map()
  for (const [group, items] of groupedTools.value) {
    const matching = items.filter(
      t => t.key.includes(q)
        || formatKey(t.key).toLowerCase().includes(q)
        || t.description?.toLowerCase().includes(q)
    )
    if (matching.length) result.set(group, matching)
  }
  return result
})

const filteredCount = computed(() =>
  [...visibleGroups.value.values()].reduce((n, items) => n + items.length, 0)
)

// ── Section collapse ───────────────────────────────────────────────────────

function isOpen(group) {
  if (filter.value.trim()) return true
  return expanded.value.includes(group)
}

function toggleSection(group) {
  const i = expanded.value.indexOf(group)
  if (i >= 0) expanded.value.splice(i, 1)
  else expanded.value.push(group)
}

// ── Click handling ─────────────────────────────────────────────────────────

function handleClick(tool) {
  if (tool.params?.length) {
    dialogTool.value = tool
    selected.value = null
  } else {
    selected.value = tool
  }
}

// ── Selection & conflict (for no-param tools) ──────────────────────────────

const isRunning = key => props.runningJobs.includes(key)

const blockers = computed(() => {
  if (!selected.value || selected.value.readonly) return []
  const group = selected.value.parallelism_group
  if (!group) return []
  return props.runningJobs.filter(runningKey => {
    const t = tools.value.find(x => x.key === runningKey)
    return t && t.parallelism_group === group
  })
})

function launch() {
  if (!selected.value || blockers.value.length) return
  emit('launch', selected.value, {})
}

function onDialogLaunch(tool, params) {
  dialogTool.value = null
  emit('launch', tool, params)
}

function onReportLaunch(selectedReports, formats) {
  showReportDialog.value = false
  emit('launch-reports', selectedReports, formats)
}
</script>

<style scoped>
.picker {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

/* ── Filter ── */
.picker-filter {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.65rem 1rem;
  border-bottom: 1px solid var(--border);
}
.filter-wrap {
  flex: 1;
  position: relative;
  display: flex;
  align-items: center;
}
.filter-input {
  flex: 1;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 5px;
  color: var(--text-1);
  padding: 5px 28px 5px 9px;
  font-size: 0.85rem;
  outline: none;
  transition: border-color 0.15s;
  width: 100%;
}
.filter-input:focus        { border-color: var(--action); }
.filter-input::placeholder { color: var(--text-3); }
.filter-clear {
  position: absolute;
  right: 6px;
  background: none;
  border: none;
  color: var(--text-3);
  cursor: pointer;
  font-size: 1rem;
  line-height: 1;
  padding: 0 2px;
}
.filter-clear:hover { color: var(--text-1); }
.filter-count { color: var(--text-3); font-size: 0.75rem; white-space: nowrap; }

/* ── Scrollable body ── */
.picker-body {
  flex: 1;
  overflow-y: auto;
  padding: 0.25rem 0;
}

/* ── Group ── */
.group { border-bottom: 1px solid var(--border); }

.group-header {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.45rem 1rem;
  background: var(--surface-alt);
  border: none;
  color: var(--text-2);
  cursor: pointer;
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.07em;
  text-transform: uppercase;
  text-align: left;
  transition: background 0.12s;
}
.group-header:hover { background: var(--border); }
.chevron    { font-size: 0.6rem; color: var(--text-3); }
.group-name { flex: 1; }
.group-count {
  font-size: 0.7rem;
  color: var(--text-3);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 0 6px;
}

/* ── Items ── */
.group-items {
  list-style: none;
  margin: 0;
  padding: 0.25rem 0;
}
.job-item {
  padding: 0.45rem 1rem;
  cursor: pointer;
  transition: background 0.1s;
  border-left: 2px solid transparent;
}
.job-item:hover       { background: var(--surface-alt); }
.job-item.selected    { background: color-mix(in srgb, var(--action) 12%, transparent); border-left-color: var(--action); }
.job-item.running     { border-left-color: var(--badge-run-text); }
.job-item.configurable:hover { border-left-color: var(--accent); }

.item-top {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  margin-bottom: 2px;
}
.item-name {
  font-size: 0.85rem;
  color: var(--text-1);
  font-weight: 500;
  flex: 1;
}
.item-desc {
  font-size: 0.76rem;
  color: var(--text-2);
  line-height: 1.35;
}

/* ── Badges ── */
.badge {
  font-size: 0.68rem;
  border-radius: 3px;
  padding: 1px 5px;
  font-weight: 600;
  white-space: nowrap;
  flex-shrink: 0;
}
.badge-ro  { background: var(--badge-ro-bg);  color: var(--badge-ro-text); }
.badge-run { background: var(--badge-run-bg); color: var(--badge-run-text); }
.badge-cfg { background: var(--surface-alt); color: var(--accent); border: 1px solid var(--accent); }

/* ── State messages ── */
.state-msg   { padding: 1.5rem 1rem; color: var(--text-2); font-size: 0.85rem; text-align: center; }
.state-error { color: #f87171; }

/* ── Launch area ── */
.launch-area {
  flex-shrink: 0;
  border-top: 1px solid var(--border);
  padding: 0.65rem 1rem;
  background: var(--surface);
}
.launch-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-top: 0.4rem;
}
.launch-selection {
  flex: 1;
  font-size: 0.85rem;
  color: var(--text-1);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.launch-selection.dim { color: var(--text-3); font-weight: 400; }
.launch-btn {
  flex-shrink: 0;
  padding: 6px 18px;
  background: var(--action);
  color: #fff;
  border: none;
  border-radius: 5px;
  cursor: pointer;
  font-size: 0.85rem;
  font-weight: 500;
  transition: background 0.15s;
}
.launch-btn:hover:not(:disabled) { background: var(--action-hover); }
.launch-btn:disabled {
  background: var(--action-off);
  color: var(--action-off-text);
  cursor: not-allowed;
}
.reports-row {
  border-top: 1px solid var(--border);
  padding-top: 0.5rem;
  margin-top: 0.35rem;
}
.reports-btn {
  width: 100%;
  padding: 7px 0;
  background: transparent;
  border: 1px solid var(--border);
  border-radius: 5px;
  color: var(--text-2);
  font-size: 0.82rem;
  cursor: pointer;
  transition: border-color 0.15s, color 0.15s;
}
.reports-btn:hover {
  border-color: var(--action);
  color: var(--action);
}
</style>
