<template>
  <div class="app-shell">
    <NavBar />
    <div class="workspace">

      <aside class="sidebar">
        <div class="sidebar-picker">
          <JobPicker :running-jobs="runningJobs" @launch="onLaunch" />
        </div>
        <div class="sidebar-footer">
          <a href="/" target="_blank" rel="noopener" class="reports-link">
            Reports&thinsp;↗
          </a>
        </div>
      </aside>

      <main class="main-pane">
        <!-- E3: JobRunner tabs + streaming log pane goes here -->
        <div class="placeholder">
          <span class="placeholder-icon">⚙</span>
          <p>Select a job and click Launch to run it.</p>
          <p class="placeholder-sub">Job runner and log pane coming in E3.</p>
        </div>
      </main>

    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import NavBar  from '../components/NavBar.vue'
import JobPicker from '../components/JobPicker.vue'

// Populated by WebSocket job events — wired in E3.
const runningJobs = ref([])

function onLaunch(job, params) {
  console.log('launch', job.key, params)
}
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
  overflow: auto;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg);
}

.placeholder {
  text-align: center;
  color: var(--text-2);
}
.placeholder-icon {
  font-size: 2rem;
  display: block;
  margin-bottom: 0.5rem;
  opacity: 0.4;
}
.placeholder p { margin: 0.2rem 0; font-size: 0.9rem; }
.placeholder-sub { font-size: 0.78rem; color: var(--text-3); }
</style>
