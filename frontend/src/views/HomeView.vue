<template>
  <div class="app-shell">
    <NavBar />
    <div class="workspace">

      <aside class="sidebar">
        <div class="sidebar-picker">
          <JobPicker :running-jobs="runningJobKeys" @launch="onLaunch" @launch-reports="onLaunchReports" />
        </div>
        <div class="sidebar-footer">
          <a href="/" target="_blank" rel="noopener" class="reports-link">
            Reports&thinsp;↗
          </a>
        </div>
      </aside>

      <main class="main-pane">
        <JobRunner />
      </main>

    </div>
  </div>
</template>

<script setup>
import NavBar    from '../components/NavBar.vue'
import JobPicker from '../components/JobPicker.vue'
import JobRunner from './JobRunner.vue'
import { useJobs } from '../composables/useJobs.js'

const { runningJobKeys, launch, launchReports } = useJobs()

function onLaunch(job, params)          { launch(job, params) }
function onLaunchReports(reports, fmts) { launchReports(reports, fmts) }
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
}
.reports-link {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  font-size: 0.82rem;
  font-weight: 500;
  color: var(--action);
}
.reports-link:hover { color: var(--action-hover); }

/* ── Main pane ── */
.main-pane {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  background: var(--bg);
}
</style>
