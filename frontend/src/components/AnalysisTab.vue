<!-- Analysis tab of the side panel (issue #169): portfolio analysis tools
     computed from report snapshots. First capability: the Blocked Work
     Explorer. Future analyses append to the ANALYSES list. -->
<template>
  <div class="analysis-tab">
    <button
      v-for="a in ANALYSES" :key="a.key"
      class="analysis-row"
      :class="{ active: mainView === 'analysis' }"
      @click="openAnalysis()"
    >
      <span class="analysis-name">{{ a.name }}</span>
      <span class="analysis-desc">{{ a.desc }}</span>
    </button>
  </div>
</template>

<script setup>
import { useMainView } from '../composables/useMainView.js'

const { mainView, openAnalysis } = useMainView()

const ANALYSES = [
  {
    key: 'portfolio',
    name: 'Portfolio Explorer',
    desc: 'Every portfolio epic (epic::epic) with attention drawn to blocked work and schedule risk',
  },
]
</script>

<style scoped>
.analysis-tab {
  flex: 1;
  overflow-y: auto;
  padding: 0.5rem 0;
}
.analysis-row {
  display: block;
  width: 100%;
  text-align: left;
  background: none;
  border: none;
  border-left: 2px solid transparent;
  padding: 0.6rem 1rem;
  cursor: pointer;
  transition: background 0.12s;
}
.analysis-row:hover  { background: var(--surface-alt); }
.analysis-row.active { background: var(--surface-alt); border-left-color: var(--action); }
.analysis-name {
  display: block;
  font-size: 0.86rem;
  font-weight: 600;
  color: var(--text-1);
  margin-bottom: 0.2rem;
}
.analysis-desc {
  display: block;
  font-size: 0.76rem;
  color: var(--text-3);
  line-height: 1.4;
}
</style>
