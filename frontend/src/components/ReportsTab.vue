<!-- Reports tab of the side panel (issue #167): browse report snapshot runs
     and open wiki pages in the in-app markdown viewer. The page list mirrors
     the GitLab wiki hierarchy exactly (paths come from the run's pages.json
     manifest), with a filter box matching the Tools tab's. Run Reports… is
     pinned at the bottom, same as on the Tools tab (issue #170). -->
<template>
  <div class="reports-tab">

    <div v-if="loading" class="empty-state">Loading runs…</div>

    <div v-else-if="!wikiRuns.length" class="empty-state">
      No report snapshots yet.<br>
      Run reports from the Tools tab to populate this list.
    </div>

    <template v-else>
      <div class="run-row">
        <label class="run-label" for="report-run">Snapshot</label>
        <select id="report-run" v-model="selectedRun" class="run-select">
          <option v-for="r in wikiRuns" :key="r.path" :value="r">
            {{ formatRun(r) }}
          </option>
        </select>
      </div>

      <div class="reports-filter">
        <div class="filter-wrap">
          <input
            v-model="filter"
            class="filter-input"
            placeholder="Filter reports…"
            spellcheck="false"
          />
          <button
            v-if="filter"
            class="filter-clear"
            @click="filter = ''"
            aria-label="Clear filter"
          >×</button>
        </div>
        <span class="filter-count">
          {{ visiblePageCount }}&thinsp;/&thinsp;{{ pages.length }}
        </span>
      </div>

      <div class="page-list">
        <template v-for="row in rows" :key="row.key">
          <div
            v-if="row.type === 'dir'"
            class="dir-label"
            :style="{ paddingLeft: (0.75 + row.depth * 0.85) + 'rem' }"
          >{{ row.label }}</div>
          <button
            v-else
            class="page-row"
            :class="{ active: isOpen(row.page) }"
            :style="{ paddingLeft: (0.9 + row.depth * 0.85) + 'rem' }"
            :title="row.page.path || row.page.title"
            @click="open(row.page)"
          >{{ row.label }}</button>
        </template>
        <div v-if="pagesLoaded && !pages.length" class="empty-state">
          This snapshot has no wiki pages.
        </div>
        <div v-else-if="filter && !visiblePageCount" class="empty-state">
          No reports match “{{ filter }}”.
        </div>
      </div>
    </template>

    <!-- Run Reports — pinned to bottom, same affordance as the Tools tab -->
    <div class="reports-area">
      <button class="reports-btn" @click="showReportDialog = true">
        Run Reports…
      </button>
    </div>

  </div>

  <ReportPickerDialog
    v-if="showReportDialog"
    :reports="reportDefs"
    @launch="onReportLaunch"
    @close="showReportDialog = false"
  />
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { getReports } from '../api.js'
import ReportPickerDialog from './ReportPickerDialog.vue'
import { useMainView } from '../composables/useMainView.js'

const emit = defineEmits(['launch-reports'])

const { reportPage, openReport } = useMainView()

const showReportDialog = ref(false)
const reportDefs       = ref([])

function onReportLaunch(selectedReports, formats, useLast) {
  showReportDialog.value = false
  emit('launch-reports', selectedReports, formats, useLast)
}

const loading     = ref(true)
const runs        = ref([])
const selectedRun = ref(null)
const pages       = ref([])
const pagesLoaded = ref(false)
const filter      = ref('')

const wikiRuns = computed(() => runs.value.filter(r => r.has_wiki))

const filteredPages = computed(() => {
  const q = filter.value.trim().toLowerCase()
  if (!q) return pages.value
  return pages.value.filter(p =>
    (p.path || p.title).toLowerCase().includes(q))
})

const visiblePageCount = computed(() => filteredPages.value.length)

// Rows mirroring the GitLab wiki tree: pages arrive in wiki path order, and
// directory labels are emitted whenever a page's ancestor path diverges from
// the previous row's. While filtering, ancestors of matches stay visible so
// hits keep their wiki context.
const rows = computed(() => {
  const out = []
  let prevDirs = []
  for (const p of filteredPages.value) {
    // A page's directories are every segment above the leaf; legacy entries
    // (no manifest) fall back to the flat tier grouping.
    const dirs = p.segments
      ? p.segments.slice(0, -1)
      : (p.tier ? [`${p.tier} ${p.tier_name}`] : [])
    dirs.forEach((label, depth) => {
      if (prevDirs[depth] !== label) {
        out.push({ type: 'dir', key: `d:${dirs.slice(0, depth + 1).join('/')}`, label, depth })
        prevDirs = prevDirs.slice(0, depth)
        prevDirs[depth] = label
      }
    })
    prevDirs = dirs
    out.push({ type: 'page', key: `p:${p.slug}`, label: p.title, depth: dirs.length, page: p })
  }
  return out
})

function formatRun(r) {
  const d = r.date, t = r.time
  return `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6)} ${t.slice(0, 2)}:${t.slice(2, 4)}:${t.slice(4)}`
}

function isOpen(p) {
  const cur = reportPage.value
  return !!cur && cur.slug === p.slug
    && cur.date === selectedRun.value?.date
    && cur.time === selectedRun.value?.time
}

function open(p) {
  openReport({
    date:  selectedRun.value.date,
    time:  selectedRun.value.time,
    slug:  p.slug,
    title: p.title,
  })
}

async function loadPages(run) {
  pages.value = []
  pagesLoaded.value = false
  if (!run) return
  try {
    const r = await fetch(`/api/runs/${run.date}/${run.time}/wiki/index.json`)
    pages.value = r.ok ? await r.json() : []
  } catch {
    pages.value = []
  }
  pagesLoaded.value = true
}

watch(selectedRun, loadPages)

onMounted(async () => {
  try {
    const r = await fetch('/api/runs')
    runs.value = r.ok ? await r.json() : []
  } catch {
    runs.value = []
  }
  selectedRun.value = wikiRuns.value[0] || null
  loading.value = false
  try {
    reportDefs.value = await getReports()
  } catch {
    reportDefs.value = []
  }
})
</script>

<style scoped>
.reports-tab {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.run-row {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.6rem 1rem;
  border-bottom: 1px solid var(--border);
}
.run-label {
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-3);
}
.run-select {
  flex: 1;
  min-width: 0;
  background: var(--surface-alt);
  color: var(--text-1);
  border: 1px solid var(--border);
  border-radius: 4px;
  font-size: 0.8rem;
  padding: 0.3rem 0.4rem;
}

/* ── Filter (mirrors the Tools tab's) ── */
.reports-filter {
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

/* ── Wiki tree ── */
.page-list {
  flex: 1;
  overflow-y: auto;
  padding: 0.25rem 0 0.75rem;
}
.dir-label {
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-3);
  padding-top: 0.7rem;
  padding-bottom: 0.25rem;
  padding-right: 1rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.page-row {
  display: block;
  width: 100%;
  text-align: left;
  background: none;
  border: none;
  color: var(--text-2);
  font-size: 0.84rem;
  padding-top: 0.42rem;
  padding-bottom: 0.42rem;
  padding-right: 1rem;
  cursor: pointer;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  transition: background 0.12s, color 0.12s;
}
.page-row:hover  { background: var(--surface-alt); color: var(--text-1); }
.page-row.active { background: var(--surface-alt); color: var(--text-1); font-weight: 600; }

.empty-state {
  padding: 1.5rem 1rem;
  text-align: center;
  font-size: 0.8rem;
  color: var(--text-3);
  line-height: 1.5;
}

/* ── Run Reports (matches the Tools tab's) ── */
.reports-area {
  flex-shrink: 0;
  border-top: 1px solid var(--border);
  padding: 0.65rem 1rem;
  background: var(--surface);
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
@media (pointer: coarse) {
  .reports-btn { min-height: 44px; }
}
</style>
