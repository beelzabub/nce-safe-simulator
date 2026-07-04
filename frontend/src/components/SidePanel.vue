<!-- Multi-function side panel (epic #165): Tools / Reports / Analysis tabs.
     Tab pattern mirrors StatusSidebar's Server/Session bar. The Tools tab
     embeds the existing JobPicker unchanged; Reports (#167) and Analysis
     (#169) fill their bodies in follow-on features. -->
<template>
  <div class="side-panel">
    <div class="panel-header">
      <div class="tab-bar">
        <button
          v-for="t in TABS" :key="t.key"
          class="tab-btn" :class="{ active: activeTab === t.key }"
          @click="selectTab(t.key)"
        >
          {{ t.label }}
          <span v-if="t.key === 'tools' && runningJobs.length" class="tab-badge tab-badge--running">{{ runningJobs.length }}</span>
        </button>
      </div>
    </div>

    <!-- ── Tools ── -->
    <div v-show="activeTab === 'tools'" class="panel-body">
      <JobPicker
        :running-jobs="runningJobs"
        @launch="(job, params) => $emit('launch', job, params)"
        @launch-reports="(reports, fmts, useLast) => $emit('launch-reports', reports, fmts, useLast)"
      />
    </div>

    <!-- ── Reports (#167) ── -->
    <div v-if="activeTab === 'reports'" class="panel-body">
      <ReportsTab
        @launch-reports="(reports, fmts, useLast) => $emit('launch-reports', reports, fmts, useLast)"
      />
    </div>

    <!-- ── Analysis (#169) ── -->
    <div v-if="activeTab === 'analysis'" class="panel-body">
      <AnalysisTab />
    </div>

    <!-- ── External surfaces — the original sidebar footer (issue #170) ── -->
    <div class="panel-footer">
      <a href="/quarto/" target="_blank" rel="noopener" class="footer-link">Quarto&thinsp;↗</a>
      <a v-if="gitlabWikiUrl" :href="gitlabWikiUrl" target="_blank" rel="noopener" class="footer-link">GitLab&thinsp;↗</a>
      <a v-if="grafanaUrl" :href="grafanaUrl" target="_blank" rel="noopener" class="footer-link">Grafana&thinsp;↗</a>
      <a href="/api/wiki" target="_blank" rel="noopener" class="footer-link">Raw&thinsp;↗</a>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import JobPicker from './JobPicker.vue'
import ReportsTab from './ReportsTab.vue'
import AnalysisTab from './AnalysisTab.vue'
import { loadStored, saveStored } from '../composables/useLocalStorage.js'

defineProps({
  runningJobs:   { type: Array, default: () => [] },
  gitlabWikiUrl: { type: String, default: '' },
  grafanaUrl:    { type: String, default: '' },
})
defineEmits(['launch', 'launch-reports'])

const TABS = [
  { key: 'tools',    label: 'Tools' },
  { key: 'reports',  label: 'Reports' },
  { key: 'analysis', label: 'Analysis' },
]

const TAB_KEY = 'nce.sidepanel.tab'
const stored = loadStored(TAB_KEY, 'tools')
const activeTab = ref(TABS.some(t => t.key === stored) ? stored : 'tools')

function selectTab(key) {
  activeTab.value = key
  saveStored(TAB_KEY, key)
}
</script>

<style scoped>
.side-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* ── Tab bar (StatusSidebar pattern) ── */
.panel-header {
  display: flex;
  align-items: center;
  padding: 0 0.75rem;
  height: 44px;
  flex-shrink: 0;
  border-bottom: 1px solid var(--border);
}
.tab-bar {
  display: flex;
  gap: 2px;
  flex: 1;
}
.tab-btn {
  flex: 1;
  background: none;
  border: none;
  border-radius: 4px;
  color: var(--text-3);
  cursor: pointer;
  font-size: 0.78rem;
  font-weight: 500;
  letter-spacing: 0.03em;
  padding: 4px 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  transition: color 0.15s, background 0.15s;
}
.tab-btn:hover { color: var(--text-1); background: var(--surface-alt); }
.tab-btn.active { color: var(--text-1); background: var(--surface-alt); font-weight: 600; }

.tab-badge {
  font-size: 0.68rem;
  font-weight: 700;
  background: var(--border);
  color: var(--text-2);
  border-radius: 8px;
  padding: 0 5px;
  line-height: 1.5;
}
.tab-badge--running {
  background: rgba(63, 185, 80, 0.25);
  color: #3fb950;
}

/* ── Bodies ── */
.panel-body {
  flex: 1;
  overflow: hidden;   /* JobPicker manages its own internal scroll */
  min-height: 0;
  display: flex;
  flex-direction: column;
}

/* ── Footer links (restored from the pre-tab sidebar) ── */
.panel-footer {
  flex-shrink: 0;
  border-top: 1px solid var(--border);
  padding: 0.6rem 1rem;
  display: flex;
  gap: 1rem;
  justify-content: center;
}
.footer-link {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  font-size: 0.82rem;
  font-weight: 400;
  color: var(--text-3);
  text-decoration: none;
  transition: color 0.15s;
}
.footer-link:hover { color: var(--text-1); }
</style>
