<template>
  <div class="picker">

    <!-- Filter bar -->
    <div class="picker-filter">
      <input
        v-model="filter"
        class="filter-input"
        placeholder="Filter jobs…"
        spellcheck="false"
      />
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
              selected: selected?.key === t.key,
              running:  isRunning(t.key),
            }"
            @click="select(t)"
          >
            <div class="item-top">
              <span class="item-key">{{ t.key }}</span>
              <span v-if="isRunning(t.key)" class="badge badge-run">● running</span>
              <span v-else-if="t.readonly" class="badge badge-ro">read-only</span>
            </div>
            <div class="item-desc">{{ t.description }}</div>
          </li>
        </ul>
      </section>

      <div v-if="visibleGroups.size === 0 && filter" class="state-msg">
        No jobs match "{{ filter }}"
      </div>
    </div>

    <!-- Launch area — pinned to bottom of picker -->
    <div class="launch-area">
      <ConflictBanner :blockers="blockers" />
      <div class="launch-row">
        <span class="launch-selection" :class="{ dim: !selected }">
          {{ selected ? selected.key : 'Nothing selected' }}
        </span>
        <button
          class="launch-btn"
          :disabled="!selected || blockers.length > 0"
          @click="launch"
        >
          Launch
        </button>
      </div>
    </div>

  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { getTools } from '../api.js'
import ConflictBanner from './ConflictBanner.vue'

const props = defineProps({
  runningJobs: { type: Array, default: () => [] },
})
const emit = defineEmits(['launch'])

const tools    = ref([])
const selected = ref(null)
const loading  = ref(true)
const error    = ref(null)
const filter   = ref('')
const collapsed = ref([])  // group keys the user has manually closed

onMounted(async () => {
  try {
    tools.value = await getTools()
  } catch (e) {
    error.value = `Failed to load: ${e.message}`
  } finally {
    loading.value = false
  }
})

// ── Grouping ──────────────────────────────────────────────────────────────

function formatGroup(g) {
  if (g === 'read-only') return 'Read-only Tools'
  return g.split('-').map(w => w[0].toUpperCase() + w.slice(1)).join(' ')
}

const groupedTools = computed(() => {
  const groups = new Map()
  for (const t of tools.value) {
    const key = t.readonly ? 'read-only' : (t.parallelism_group ?? 'other')
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key).push(t)
  }
  // Writer groups alphabetically; read-only always last.
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
      t => t.key.includes(q) || t.description?.toLowerCase().includes(q)
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
  if (filter.value.trim()) return true   // always expand matching sections
  return !collapsed.value.includes(group)
}

function toggleSection(group) {
  const i = collapsed.value.indexOf(group)
  if (i >= 0) collapsed.value.splice(i, 1)
  else collapsed.value.push(group)
}

// ── Selection & conflict ───────────────────────────────────────────────────

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

function select(item) { selected.value = item }

function launch() {
  if (!selected.value || blockers.value.length) return
  emit('launch', selected.value)
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
.filter-input {
  flex: 1;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 5px;
  color: var(--text-1);
  padding: 5px 9px;
  font-size: 0.85rem;
  outline: none;
  transition: border-color 0.15s;
}
.filter-input:focus    { border-color: var(--action); }
.filter-input::placeholder { color: var(--text-3); }
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
.chevron { font-size: 0.6rem; color: var(--text-3); }
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
}
.job-item:hover    { background: var(--surface-alt); }
.job-item.selected { background: color-mix(in srgb, var(--action) 15%, transparent); }
.job-item.running  { border-left: 2px solid var(--badge-run-text); padding-left: calc(1rem - 2px); }

.item-top {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  margin-bottom: 1px;
}
.item-key {
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 0.82rem;
  color: var(--text-1);
  font-weight: 500;
}
.item-desc {
  font-size: 0.78rem;
  color: var(--text-2);
  line-height: 1.3;
}

/* ── Badges ── */
.badge {
  font-size: 0.68rem;
  border-radius: 3px;
  padding: 1px 5px;
  font-weight: 600;
  white-space: nowrap;
}
.badge-ro  { background: var(--badge-ro-bg);  color: var(--badge-ro-text); }
.badge-run { background: var(--badge-run-bg); color: var(--badge-run-text); }

/* ── State messages ── */
.state-msg {
  padding: 1.5rem 1rem;
  color: var(--text-2);
  font-size: 0.85rem;
  text-align: center;
}
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
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 0.82rem;
  color: var(--text-1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.launch-selection.dim { color: var(--text-3); font-family: inherit; }
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
</style>
