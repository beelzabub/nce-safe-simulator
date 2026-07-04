<!-- Reports tab of the side panel (issue #167): browse report snapshot runs
     and open wiki pages in the in-app markdown viewer. External report
     surfaces (Quarto site, GitLab wiki, Grafana) live here too, relocated
     from the old sidebar footer. -->
<template>
  <div class="reports-tab">

    <div class="links-row">
      <a href="/quarto/" target="_blank" rel="noopener" class="ext-link">Quarto&thinsp;↗</a>
      <a v-if="gitlabWikiUrl" :href="gitlabWikiUrl" target="_blank" rel="noopener" class="ext-link">GitLab&thinsp;↗</a>
      <a v-if="grafanaUrl" :href="grafanaUrl" target="_blank" rel="noopener" class="ext-link">Grafana&thinsp;↗</a>
    </div>

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

      <div class="page-list">
        <div v-for="group in groupedPages" :key="group.key" class="tier-group">
          <div class="tier-label">{{ group.label }}</div>
          <button
            v-for="p in group.pages" :key="p.slug"
            class="page-row"
            :class="{ active: isOpen(p) }"
            @click="open(p)"
          >{{ p.title }}</button>
        </div>
        <div v-if="pagesLoaded && !pages.length" class="empty-state">
          This snapshot has no wiki pages.
        </div>
      </div>
    </template>

  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useMainView } from '../composables/useMainView.js'

defineProps({
  gitlabWikiUrl: { type: String, default: '' },
  grafanaUrl:    { type: String, default: '' },
})

const { reportPage, openReport } = useMainView()

const loading     = ref(true)
const runs        = ref([])
const selectedRun = ref(null)
const pages       = ref([])
const pagesLoaded = ref(false)

const wikiRuns = computed(() => runs.value.filter(r => r.has_wiki))

const TIER_FALLBACK = 'Portfolio Home'

const groupedPages = computed(() => {
  const groups = new Map()
  for (const p of pages.value) {
    const key = p.tier ?? ''
    if (!groups.has(key)) {
      groups.set(key, {
        key,
        label: p.tier ? `${p.tier} · ${p.tier_name}` : TIER_FALLBACK,
        pages: [],
      })
    }
    groups.get(key).pages.push(p)
  }
  return [...groups.values()]
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
})
</script>

<style scoped>
.reports-tab {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.links-row {
  flex-shrink: 0;
  display: flex;
  gap: 1rem;
  justify-content: center;
  padding: 0.6rem 1rem;
  border-bottom: 1px solid var(--border);
}
.ext-link {
  font-size: 0.82rem;
  color: var(--text-3);
  text-decoration: none;
  transition: color 0.15s;
}
.ext-link:hover { color: var(--text-1); }

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

.page-list {
  flex: 1;
  overflow-y: auto;
  padding: 0.25rem 0 0.75rem;
}
.tier-label {
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-3);
  padding: 0.7rem 1rem 0.25rem;
}
.page-row {
  display: block;
  width: 100%;
  text-align: left;
  background: none;
  border: none;
  color: var(--text-2);
  font-size: 0.84rem;
  padding: 0.42rem 1rem 0.42rem 1.35rem;
  cursor: pointer;
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
</style>
