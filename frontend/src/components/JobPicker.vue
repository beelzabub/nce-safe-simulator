<template>
  <div class="job-picker">
    <div v-if="error" class="load-error">{{ error }}</div>
    <div v-else-if="loading">Loading jobs…</div>

    <template v-else>
      <!-- Reports -->
      <section>
        <h3>Reports</h3>
        <ul>
          <li
            v-for="r in reports"
            :key="r.key"
            :class="{ selected: selected?.key === r.key }"
            @click="select(r)"
          >
            {{ r.key }}
          </li>
        </ul>
      </section>

      <!-- Tools grouped by parallelism_group; read-only tools collected at end -->
      <section v-for="[group, items] in groupedTools" :key="group">
        <h3>{{ group }}</h3>
        <ul>
          <li
            v-for="t in items"
            :key="t.key"
            :class="{ selected: selected?.key === t.key }"
            @click="select(t)"
          >
            {{ t.key }}
            <span v-if="t.readonly" class="badge">read-only</span>
          </li>
        </ul>
      </section>

      <!-- Conflict warning -->
      <ConflictBanner :blockers="blockers" />

      <!-- Launch -->
      <button
        class="launch-btn"
        :disabled="!selected || blockers.length > 0"
        @click="launch"
      >
        Launch{{ selected ? ': ' + selected.key : '' }}
      </button>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { getTools, getReports } from '../api.js'
import ConflictBanner from './ConflictBanner.vue'

const props = defineProps({
  // Keys of jobs currently running — provided by parent via WebSocket (wired in E3).
  runningJobs: { type: Array, default: () => [] },
})

const emit = defineEmits(['launch'])

const tools   = ref([])
const reports = ref([])
const selected = ref(null)
const loading  = ref(true)
const error    = ref(null)

onMounted(async () => {
  try {
    const [toolsData, reportsData] = await Promise.all([getTools(), getReports()])
    tools.value   = toolsData
    reports.value = reportsData.map(r => ({ ...r, isReport: true }))
  } catch (e) {
    error.value = `Failed to load jobs: ${e.message}`
  } finally {
    loading.value = false
  }
})

// Group tools: writers by parallelism_group, then a single "Read-only" bucket.
const groupedTools = computed(() => {
  const groups = new Map()
  for (const t of tools.value) {
    const key = t.parallelism_group ?? 'read-only'
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key).push(t)
  }
  // Put read-only last
  const sorted = new Map(
    [...groups.entries()].sort(([a], [b]) =>
      a === 'read-only' ? 1 : b === 'read-only' ? -1 : a.localeCompare(b)
    )
  )
  return sorted
})

// Conflict check: read-only jobs never conflict; writers conflict when a running
// job shares the same parallelism_group.
const blockers = computed(() => {
  if (!selected.value || selected.value.readonly) return []
  const group = selected.value.parallelism_group
  if (!group) return []
  return props.runningJobs.filter(runningKey => {
    const t = tools.value.find(x => x.key === runningKey)
    return t && t.parallelism_group === group
  })
})

function select(item) {
  selected.value = item
}

function launch() {
  if (!selected.value || blockers.value.length) return
  emit('launch', selected.value)
}
</script>

<style scoped>
.job-picker {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  max-width: 640px;
}
section {
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  padding: 0.75rem 1rem;
}
h3 {
  margin: 0 0 0.5rem;
  font-size: 0.8rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #6b7280;
}
ul {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
li {
  padding: 5px 8px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.9rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
li:hover    { background: #f3f4f6; }
li.selected { background: #dbeafe; }
.badge {
  font-size: 0.7rem;
  background: #e0f2fe;
  color: #0369a1;
  border-radius: 3px;
  padding: 1px 5px;
}
.launch-btn {
  align-self: flex-start;
  padding: 8px 20px;
  background: #2563eb;
  color: #fff;
  border: none;
  border-radius: 5px;
  cursor: pointer;
  font-size: 0.9rem;
}
.launch-btn:disabled {
  background: #93c5fd;
  cursor: not-allowed;
}
.load-error {
  color: #b91c1c;
  font-size: 0.9rem;
}
</style>
