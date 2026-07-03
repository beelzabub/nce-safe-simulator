<template>
  <div class="app-shell">
    <NavBar :running-count="runningJobKeys.length" @toggle-jobs="sidebarOpen = !sidebarOpen" @toggle-status="showStatus = !showStatus" @toggle-config="showConfig = true" @toggle-help="showHelp = !showHelp" />
    <div class="workspace">

      <!-- Mobile only: dims the workspace while the jobs drawer is out -->
      <div v-if="sidebarOpen" class="sidebar-backdrop" @click="sidebarOpen = false" />

      <aside class="sidebar" :class="{ 'sidebar--open': sidebarOpen }">
        <div class="sidebar-picker">
          <JobPicker :running-jobs="runningJobKeys" @launch="onLaunch" @launch-reports="onLaunchReports" />
        </div>
        <div class="sidebar-footer">
          <a href="/quarto/" target="_blank" rel="noopener" class="reports-link">
            Quarto&thinsp;↗
          </a>
          <a v-if="gitlabWikiUrl" :href="gitlabWikiUrl" target="_blank" rel="noopener" class="reports-link">
            GitLab&thinsp;↗
          </a>
          <a v-if="grafanaUrl" :href="grafanaUrl" target="_blank" rel="noopener" class="reports-link">
            Grafana&thinsp;↗
          </a>
          <a href="/api/wiki" target="_blank" rel="noopener" class="reports-link">
            Raw&thinsp;↗
          </a>
        </div>
      </aside>

      <main class="main-pane">
        <JobRunner />
      </main>

      <StatusSidebar :open="showStatus" @close="showStatus = false" />

    </div>

    <CommandBar />

    <ConfigDialog       v-if="showConfig"       @close="showConfig = false" />
    <HelpDialog         v-if="showHelp"         @close="showHelp = false" />
    <ArchitectureDialog v-if="showArchitecture" :deployment-type="deploymentType" @close="showArchitecture = false" />
    <ArchitectureButton v-if="deploymentType" @open="showArchitecture = true" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import NavBar        from '../components/NavBar.vue'
import JobPicker     from '../components/JobPicker.vue'
import JobRunner     from './JobRunner.vue'
import StatusSidebar from '../components/StatusSidebar.vue'
import CommandBar    from '../components/CommandBar.vue'
import HelpDialog          from '../components/HelpDialog.vue'
import ConfigDialog        from '../components/ConfigDialog.vue'
import ArchitectureButton  from '../components/ArchitectureButton.vue'
import ArchitectureDialog  from '../components/ArchitectureDialog.vue'
import { useJobs }         from '../composables/useJobs.js'

const { runningJobKeys, launch, launchReports, loadDiskHistory } = useJobs()

// Below the mobile breakpoint the sidebar is an off-canvas drawer; start it
// open there so first-time phone users land on the job list, not an empty
// runner pane. On desktop the flag has no visual effect.
const isMobile = window.matchMedia('(max-width: 768px)')
const sidebarOpen = ref(isMobile.matches)

const showStatus       = ref(false)
const showConfig       = ref(false)
const showHelp         = ref(false)
const showArchitecture = ref(false)
const gitlabWikiUrl  = ref('')
const grafanaUrl     = ref('')
const deploymentType = ref('')

onMounted(async () => {
  loadDiskHistory()
  try {
    const r = await fetch('/api/config')
    if (r.ok) {
      const data = await r.json()
      gitlabWikiUrl.value  = data.wiki_url        || ''
      grafanaUrl.value     = data.grafana_url     || ''
      deploymentType.value = data.deployment_type || ''
    }
  } catch { /* server not yet ready */ }
})

function onLaunch(job, params) {
  launch(job, params)
  if (isMobile.matches) sidebarOpen.value = false   // reveal the runner pane
}
function onLaunchReports(reports, fmts, useLast) {
  launchReports(reports, fmts, useLast)
  if (isMobile.matches) sidebarOpen.value = false
}
</script>

<style scoped>
.app-shell {
  display: flex;
  flex-direction: column;
  height: 100vh;   /* fallback for browsers without dvh */
  height: 100dvh;  /* tracks the real visible height under mobile URL bars */
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
  position: relative;
  isolation: isolate;   /* own stacking context so the z-index:-1 watermark
                           paints above this pane's --bg fill, not behind it */
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  background: var(--bg);
}

/* Faint NCE emblem watermark, anchored bottom-right behind the content.
   z-index:-1 paints it above the pane's --bg fill but below .runner content.
   Theme-swapped: white emblem on dark, navy on light. */
.main-pane::after {
  content: '';
  position: absolute;
  right: clamp(16px, 3vw, 48px);
  bottom: clamp(12px, 3vw, 40px);
  width: clamp(162px, 25.5%, 306px);
  aspect-ratio: 264 / 238;
  background-image: url('../assets/nce-logo-white.png');
  background-repeat: no-repeat;
  background-position: bottom right;
  background-size: contain;
  opacity: 0.07;
  pointer-events: none;
  z-index: -1;
}
[data-theme="light"] .main-pane::after {
  background-image: url('../assets/nce-logo-navy.png');
  opacity: 0.09;
}

/* ── Mobile: sidebar becomes an off-canvas drawer (issue #160) ── */
.sidebar-backdrop { display: none; }

@media (max-width: 768px) {
  .workspace { position: relative; }

  .sidebar {
    position: absolute;
    top: 0;
    bottom: 0;
    left: 0;
    width: min(340px, 85vw);
    z-index: 50;
    transform: translateX(-105%);
    transition: transform 0.25s ease;
    box-shadow: 4px 0 24px rgba(0, 0, 0, 0.35);
  }
  .sidebar--open { transform: translateX(0); }

  .sidebar-backdrop {
    display: block;
    position: absolute;
    inset: 0;
    z-index: 40;
    background: rgba(0, 0, 0, 0.45);
  }

  /* Keep the watermark out of the way of log output on small screens */
  .main-pane::after { width: 120px; opacity: 0.05; }
}

@media (prefers-reduced-motion: reduce) {
  .sidebar { transition: none; }
}
</style>
