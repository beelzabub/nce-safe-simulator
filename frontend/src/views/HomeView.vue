<template>
  <div class="app-shell">
    <nav class="nav-bar">
      <span class="nav-brand">NCE Safe Simulator</span>
    </nav>
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
import JobPicker  from '../components/JobPicker.vue'
import JobRunner  from './JobRunner.vue'
import { useJobs } from '../composables/useJobs.js'

const { runningJobKeys, launch, launchReports } = useJobs()

function onLaunch(job, params) {
  launch(job, params)
}

function onLaunchReports(reports, formats) {
  launchReports(reports, formats)
}
</script>

<style scoped>
.app-shell {
  display: flex;
  flex-direction: column;
  height: 100vh;
}

/* ── Nav bar ── */
.nav-bar {
  flex-shrink: 0;
  height: 44px;
  display: flex;
  align-items: center;
  padding: 0 1rem;
  background: #161b22;
  border-bottom: 2px solid #fc6d26;
}
.nav-brand {
  font-size: 0.9rem;
  font-weight: 600;
  color: #e6edf3;
  letter-spacing: 0.02em;
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
  background: #161b22;
  border-right: 1px solid #30363d;
  overflow: hidden;
}
.sidebar-picker {
  flex: 1;
  overflow: hidden;
}
.sidebar-footer {
  flex-shrink: 0;
  border-top: 1px solid #30363d;
  padding: 0.6rem 1rem;
}
.reports-link {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  font-size: 0.82rem;
  font-weight: 500;
  color: #2563eb;
  text-decoration: none;
}
.reports-link:hover { color: #3b82f6; }

/* ── Main pane ── */
.main-pane {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  background: #0d1117;
}
</style>
