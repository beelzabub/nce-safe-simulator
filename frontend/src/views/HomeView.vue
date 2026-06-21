<template>
  <div class="app-shell">
    <NavBar :running-count="runningJobKeys.length" @toggle-status="showStatus = !showStatus" @toggle-config="showConfig = true" @toggle-help="showHelp = !showHelp" />
    <div class="workspace">

      <aside class="sidebar">
        <div class="sidebar-picker">
          <JobPicker :running-jobs="runningJobKeys" @launch="onLaunch" @launch-reports="onLaunchReports" />
        </div>
        <div class="sidebar-footer">
          <a href="/quarto/" target="_blank" rel="noopener" class="reports-link">
            Quarto&thinsp;↗
          </a>
          <a href="/api/wiki" target="_blank" rel="noopener" class="reports-link">
            Wiki&thinsp;↗
          </a>
          <a v-if="gitlabWikiUrl" :href="gitlabWikiUrl" target="_blank" rel="noopener" class="reports-link">
            GitLab&thinsp;↗
          </a>
        </div>
      </aside>

      <main class="main-pane">
        <JobRunner />
      </main>

      <StatusSidebar :open="showStatus" @close="showStatus = false" />

    </div>

    <ConfigDialog v-if="showConfig" @close="showConfig = false" />
    <HelpDialog   v-if="showHelp"   @close="showHelp = false" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import NavBar        from '../components/NavBar.vue'
import JobPicker     from '../components/JobPicker.vue'
import JobRunner     from './JobRunner.vue'
import StatusSidebar from '../components/StatusSidebar.vue'
import HelpDialog    from '../components/HelpDialog.vue'
import ConfigDialog  from '../components/ConfigDialog.vue'
import { useJobs }   from '../composables/useJobs.js'

const { runningJobKeys, launch, launchReports, loadDiskHistory } = useJobs()

const showStatus    = ref(false)
const showConfig    = ref(false)
const showHelp      = ref(false)
const gitlabWikiUrl = ref('')

onMounted(async () => {
  loadDiskHistory()
  try {
    const r = await fetch('/api/config')
    if (r.ok) {
      const data = await r.json()
      gitlabWikiUrl.value = data.wiki_url || ''
    }
  } catch { /* server not yet ready */ }
})

function onLaunch(job, params)          { launch(job, params) }
function onLaunchReports(reports, fmts, useLast) { launchReports(reports, fmts, useLast) }
</script>

<style scoped>
.app-shell {
  display: flex;
  flex-direction: column;
  height: 100vh;
}

/* ── Two-column workspace ── */
.workspace {
  flex: 1;
  display: flex;
  overflow: hidden;
}

/* ── Sidebar ── */
.sidebar {
  width: 340px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: var(--surface);
  border-right: 1px solid var(--border);
  overflow: hidden;
}

.sidebar-picker {
  flex: 1;
  overflow: hidden;   /* JobPicker manages its own internal scroll */
}

.sidebar-footer {
  flex-shrink: 0;
  border-top: 1px solid var(--border);
  padding: 0.6rem 1rem;
  display: flex;
  gap: 1rem;
  justify-content: center;
}
.reports-link {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  font-size: 0.82rem;
  font-weight: 400;
  color: var(--text-3);
  text-decoration: none;
  transition: color 0.15s;
}
.reports-link:hover { color: var(--text-1); }

/* ── Main pane ── */
.main-pane {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  background: var(--bg);
}
</style>
